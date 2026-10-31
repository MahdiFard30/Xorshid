// Pure restart decision: 0 = wait, 1 = process current lease, 2 = protective close.
#ifdef __cplusplus
#include <cmath>
#define KH_FINITE(v) std::isfinite(v)
#define KH_FLOOR(v) std::floor(v)
#define KH_CEIL(v) std::ceil(v)
#else
#define KH_FINITE(v) MathIsValidNumber(v)
#define KH_FLOOR(v) MathFloor(v)
#define KH_CEIL(v) MathCeil(v)
#endif
// Shared MQL/C++ budget: user-selected entry/symbol caps plus gross/USD caps.
double AllocationBudget(double equity,double fraction,double symbol_cap,double used,double total,double usd_used,double gross_cap=.005) {
 if(!KH_FINITE(equity) || !KH_FINITE(fraction) || !KH_FINITE(symbol_cap) || !KH_FINITE(used) || !KH_FINITE(total) || !KH_FINITE(usd_used)) return -1;
 if(equity<=0 || fraction<=0 || fraction>gross_cap || symbol_cap<fraction || symbol_cap>gross_cap || used<0 || total<0 || usd_used<0) return -1;
 double budget=equity*fraction;
 double limits[3]={equity*symbol_cap-used,equity*gross_cap-total,equity*gross_cap-usd_used};
 for(int i=0;i<3;i++) if(limits[i]<budget) budget=limits[i];
 return budget>0 ? budget:0;
}
// 0=hold, 1=full exit, 2=one partial exit. Cash is an estimate after a buffer.
int ManagedExitAction(double progress,bool strong,bool partial_consumed,double net,double cost_buffer) {
 if(!KH_FINITE(progress) || !KH_FINITE(net) || !KH_FINITE(cost_buffer) || cost_buffer<0) return 0;
 if(net<=cost_buffer) return 0;
 if(!strong) return progress>=1. ? 1:0;
 if(progress>=2.) return 1;
 if(progress>=1. && !partial_consumed) return 2;
 return 0;
}
// Never round above half the original volume; leave a valid remaining lot.
double ManagedPartialVolume(double original,double current,double minimum,double step) {
 if(!KH_FINITE(original) || !KH_FINITE(current) || !KH_FINITE(minimum) || !KH_FINITE(step)
    || original<=0 || current<=0 || minimum<=0 || step<=0) return 0;
 if(current<=original*.5+step*.01) return 0;
 double limit=original*.5<current-minimum ? original*.5:current-minimum;
 double result=KH_FLOOR(limit/step+1e-9)*step;
 return result>=minimum-step*.01 && current-result>=minimum-step*.01 ? result:0;
}
double ManagedStop(int side,double entry,double price,double distance,double old,double tick,double minimum) {
 if((side!=1 && side!=-1) || !KH_FINITE(entry) || !KH_FINITE(price) || !KH_FINITE(distance)
    || !KH_FINITE(old) || !KH_FINITE(tick) || !KH_FINITE(minimum)
    || entry<=0 || price<=0 || distance<=0 || old<0 || tick<=0 || minimum<0
    || side*(price-entry)<distance) return 0;
 double wanted=price-side*distance*.5;
 if(side*(wanted-entry)<0) wanted=entry;
 wanted=(side>0 ? KH_FLOOR(wanted/tick):KH_CEIL(wanted/tick))*tick;
 if(side*(price-wanted)<minimum || (old>0 && side*(wanted-old)<=tick*.5)) return 0;
 return wanted;
}
// Restart-proof entry pause. Closed deal times and now use broker-server seconds.
long EntryPauseUntil(long now,long period,long last_exit,int stops,long last_stop,int global_stops,long last_global_stop,
                     int cooldown=1,bool cluster=true,int lock_bars=4,int symbol_limit=2,int account_limit=3) {
 if(now<=0 || period<=0 || period>86400 || last_exit<0 || last_stop<0 || last_global_stop<0
    || last_exit>now || last_stop>now || last_global_stop>now || stops<0 || global_stops<0) return -1;
 long until=last_exit>0 ? last_exit+cooldown*period:0;
 if(cluster && stops>=symbol_limit && last_stop>0 && last_stop+lock_bars*period>until) until=last_stop+lock_bars*period;
 if(cluster && global_stops>=account_limit && last_global_stop>0 && last_global_stop+lock_bars*period>until) until=last_global_stop+lock_bars*period;
 return until>now ? until:0;
}
// Validate data before updating persistent account-risk baselines.
bool RiskQuoteData(double bid,double ask,long stamp,long stamp_ms,long now,long maximum_age=5) {
 return KH_FINITE(bid) && KH_FINITE(ask) && bid>0 && ask>=bid
        && stamp>0 && stamp_ms/1000==stamp && now>=stamp && maximum_age>=0 && now-stamp<=maximum_age;
}
bool RiskEquityData(double balance,double credit,double equity,double profit,double swap) {
 if(!KH_FINITE(balance) || !KH_FINITE(credit) || !KH_FINITE(equity) || !KH_FINITE(profit) || !KH_FINITE(swap)) return false;
 double difference=equity-(balance+credit+profit+swap);
 if(difference<0) difference=-difference;
 double magnitude=equity<0 ? -equity:equity;
 return difference<=.10+magnitude*1e-8;
}
#undef KH_FINITE
#undef KH_FLOOR
#undef KH_CEIL

// Kept free of terminal APIs so the same logic can be tested offline.
int RestartPolicy(bool stop_requested,bool active_lease,bool reconciled,long elapsed_ms,bool protected_positions) {
 if(stop_requested) return 2;
 if(active_lease) return 1;
 if(!reconciled && elapsed_ms>=0 && elapsed_ms<15000 && protected_positions) return 0;
 return 2;
}

// Shared MQL/C++ schedule logic. Input intervals use broker-server seconds.
// Merge overlapping sessions before detecting breaks of at least 24 hours.
bool TradingSessionOffsets(long begin,long finish,long &from,long &to) {
 // Broker can return true for an empty Saturday row (0 -> 0).
 // An explicit full day (0 -> 86400) must remain a full day.
 if(begin<0 || finish<0 || begin==finish) return false;
 from=begin%86400; to=finish%86400;
 if(to<=from) to+=86400;
 return true;
}
#ifdef __cplusplus
#define KH_SESSION_ARRAY(name) long* name
#else
#define KH_SESSION_ARRAY(name) long &name[]
#endif
int WeeklyClosePolicy(long now,KH_SESSION_ARRAY(starts),KH_SESSION_ARRAY(ends),int count,long &closes,long &opens,int lead=600) {
 closes=0; opens=0;
 if(now<=0 || count<2) return -1;
 for(int i=0;i<count;i++) {
  if(ends[i]<=starts[i]) return -1;
  for(int j=i+1;j<count;j++) {
   if(starts[j]<starts[i]) {
    long value=starts[i]; starts[i]=starts[j]; starts[j]=value;
    value=ends[i]; ends[i]=ends[j]; ends[j]=value;
   }
  }
 }
 if(now<starts[0] || now>=ends[count-1]) return -1;
 long end=ends[0];
 for(int i=1;i<count;i++) {
  if(starts[i]-end>=86400 && now<starts[i]) {
   closes=end; opens=starts[i];
   return now>=end-lead ? 1:0;
  }
  if(ends[i]>end) end=ends[i];
 }
 return 0;
}
#undef KH_SESSION_ARRAY

// Retain unfinished weekly exits across reopening and terminal restarts.
bool WeeklyExitPending(bool pending,int state,bool connected,int positions) {
 if(state==1 && positions>0) return true;
 if(pending && !(connected && positions==0)) return true;
 return false;
}
