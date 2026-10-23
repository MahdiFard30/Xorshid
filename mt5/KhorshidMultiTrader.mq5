#property strict
#property version "3.51"
#property description "DEMO ONLY: Khorshid deterministic strategy executor, SL/TP, lease and stop control."
#include <Trade/Trade.mqh>
#include "RestartPolicy.mqh"
CTrade trade;
ulong MAGIC=0;
string owner_key;
string risk_key;
string BASE;
string key;
string last_note="Idle: waiting for trainer";
bool halted=false;
bool owns=false;
long initial_login=0;
string executor_instance="";
ulong startup_started=0;
bool startup_reconciled=false;
int weekly_state=-1;
long weekly_close_at=0,weekly_open_at=0;
datetime weekly_checked=0;
ulong weekly_last_close_try=0;
bool weekly_liquidation_pending=false;
int control_cooldown=1,control_window=8,control_lock=4,control_symbol_stops=2,control_account_stops=3;
bool control_cluster=true;
int control_positions=1,control_entry_seconds=300,control_weekly_lead=600;
double control_entry_fraction=.5,control_daily=.02,control_drawdown=.10,control_margin=.20,control_spread=.10;
double control_gross_cap=.005;
string controls_revision="legacy";
void LoadControls() {
 int h=FileOpen("khorshid_multi\\shared-controls.tsv",FILE_READ|FILE_CSV|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE,'\t',CP_UTF8);
 if(h==INVALID_HANDLE) return;
 while(!FileIsEnding(h)) {
  string name=FileReadString(h),raw=FileReadString(h);double value=StringToDouble(raw);
  if(name=="revision") controls_revision=raw;
  else if(name=="cooldown_bars") control_cooldown=(int)value;
  else if(name=="stop_cluster_enabled") control_cluster=value!=0;
  else if(name=="stop_window_bars") control_window=(int)value;
  else if(name=="stop_lock_bars") control_lock=(int)value;
  else if(name=="symbol_stop_limit") control_symbol_stops=(int)value;
  else if(name=="account_stop_limit") control_account_stops=(int)value;
  else if(name=="max_positions") control_positions=(int)value;
  else if(name=="entry_window_max_seconds") control_entry_seconds=(int)value;
  else if(name=="entry_window_fraction") control_entry_fraction=value;
  else if(name=="daily_loss_fraction") control_daily=value;
  else if(name=="peak_drawdown_fraction") control_drawdown=value;
  else if(name=="margin_cap_fraction") control_margin=value;
  else if(name=="spread_atr_fraction") control_spread=value;
  else if(name=="portfolio_cap_fraction") control_gross_cap=value;
  else if(name=="weekly_close_lead_seconds") control_weekly_lead=(int)value;
 }
 FileClose(h);
}
void UpdateWeeklySchedule() {
 datetime now=TimeTradeServer();
 if(weekly_checked>0 && now>=weekly_checked && now-weekly_checked<60) {
  if(weekly_close_at>0) weekly_state=((long)now>=weekly_close_at-control_weekly_lead && (long)now<weekly_open_at) ? 1:0;
  // Rebuild at reopening rather than using an expired blackout interval.
  if(weekly_open_at==0 || (long)now<weekly_open_at) return;
 }
 weekly_checked=now;
 MqlDateTime day; TimeToStruct(now,day);
 long midnight=(long)now-day.hour*3600-day.min*60-day.sec;
 long starts[1024],ends[1024]; int count=0;
 for(int offset=-8;offset<=8;offset++) {
  datetime date=(datetime)(midnight+offset*86400);
  MqlDateTime parts; TimeToStruct(date,parts);
  for(uint index=0;index<32;index++) {
   datetime begin=0,finish=0;
   if(!SymbolInfoSessionTrade(_Symbol,(ENUM_DAY_OF_WEEK)parts.day_of_week,index,begin,finish)) break;
   MqlDateTime b,e; TimeToStruct(begin,b); TimeToStruct(finish,e);
   long from=b.hour*3600+b.min*60+b.sec;
   long to=e.hour*3600+e.min*60+e.sec;
   // Midnight end and overnight sessions belong to the following date.
   if(to<=from) to+=86400;
   starts[count]=(long)date+from; ends[count]=(long)date+to; count++;
  }
 }
 weekly_state=WeeklyClosePolicy((long)now,starts,ends,count,weekly_close_at,weekly_open_at,control_weekly_lead);
}
string Q(string s) { StringReplace(s,"\\","\\\\"); StringReplace(s,"\"","\\\""); StringReplace(s,"\r"," "); StringReplace(s,"\n"," "); StringReplace(s,"\t"," "); return "\""+s+"\""; }
string B(bool b) { return b ? "true":"false"; }
void WriteFile(string name,string body) {
 int h=FileOpen(name+".tmp",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
 if(h==INVALID_HANDLE) { Print("Khorshid write error ",GetLastError()); return; }
 FileWriteString(h,body); FileFlush(h); FileClose(h);
 if(!FileMove(name+".tmp",0,name,FILE_REWRITE)) Print("Khorshid publish error ",GetLastError());
}
bool Demo() { return AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO; }
bool CanTrade() { return Demo() && AccountInfoInteger(ACCOUNT_LOGIN)==initial_login && TerminalInfoInteger(TERMINAL_CONNECTED) && TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED) && AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) && AccountInfoInteger(ACCOUNT_TRADE_EXPERT); }
bool PortfolioMagic(long magic) { return (magic==260100931 || magic==260100932 || magic==260100934); }
int BlockingPositions() {
 int n=0;
 for(int i=PositionsTotal()-1;i>=0;i--) {
  if(PositionGetTicket(i)==0) continue;
  long magic=PositionGetInteger(POSITION_MAGIC);
  if(!PortfolioMagic(magic) || (PositionGetString(POSITION_SYMBOL)==_Symbol && (ulong)magic!=MAGIC)) n++;
 }
 return n;
}
int OwnCount() {
 int n=0; for(int i=PositionsTotal()-1;i>=0;i--) { ulong t=PositionGetTicket(i); if(t>0 && (ulong)PositionGetInteger(POSITION_MAGIC)==MAGIC) n++; } return n;
}
// Two independent positions only on hedging accounts; netting stays single-entry.
int PositionLimit() { return (int)MathMin(control_positions,AccountInfoInteger(ACCOUNT_MARGIN_MODE)==ACCOUNT_MARGIN_MODE_RETAIL_HEDGING ? 2:1); }
int EntryWindow() { return (int)MathMin(control_entry_seconds,MathMax(1,PeriodSeconds(_Period)*control_entry_fraction)); }
double OwnRisk(int direction) {
 double total=0;
 for(int i=PositionsTotal()-1;i>=0;i--) {
  if(PositionGetTicket(i)==0 || (ulong)PositionGetInteger(POSITION_MAGIC)!=MAGIC) continue;
  if(PositionGetString(POSITION_SYMBOL)!=_Symbol) return -1;
  bool buy=PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY;
  if((buy ? 1:-1)!=direction) return -1;
  double sl=PositionGetDouble(POSITION_SL),loss=0;
  if(sl<=0 || !OrderCalcProfit(buy ? ORDER_TYPE_BUY:ORDER_TYPE_SELL,_Symbol,PositionGetDouble(POSITION_VOLUME),PositionGetDouble(POSITION_PRICE_OPEN),sl,loss) || !MathIsValidNumber(loss)) return -1;
  total+=MathMax(0,-loss);
 }
 return total;
}
double PortfolioRisk(int usd_filter=0) {
 double total=0;
 for(int i=PositionsTotal()-1;i>=0;i--) {
  if(PositionGetTicket(i)==0 || !PortfolioMagic(PositionGetInteger(POSITION_MAGIC))) continue;
  string symbol=PositionGetString(POSITION_SYMBOL);
  if(symbol!="XAUUSD" && symbol!="EURUSD" && symbol!="USDJPY") return -1;
  bool buy=PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY;
  int usd_side=(symbol=="USDJPY" ? 1:-1)*(buy ? 1:-1);
  if(usd_filter!=0 && usd_side!=usd_filter) continue;
  double sl=PositionGetDouble(POSITION_SL),loss=0;
  if(sl<=0 || !OrderCalcProfit(buy ? ORDER_TYPE_BUY:ORDER_TYPE_SELL,symbol,PositionGetDouble(POSITION_VOLUME),PositionGetDouble(POSITION_PRICE_OPEN),sl,loss) || !MathIsValidNumber(loss)) return -1;
  total+=MathMax(0,-loss);
 }
 return total;
}
class AllocationLock {
 private:
  string name;
  double owner;
  bool held;
 public:
  AllocationLock(void) { held=false; }
  bool Acquire(string lock_name) {
   name=lock_name; owner=(double)ChartID();
   GlobalVariableTemp(name);
   held=GlobalVariableSetOnCondition(name,owner,0);
   return held;
  }
  ~AllocationLock(void) { if(held) GlobalVariableSetOnCondition(name,0,owner); }
};
void CloseSelected(long id,string tickets) {
 string items[]; int count=StringSplit(tickets,',',items);
 if(count<1 || count>2 || !CanTrade()) { Ack(id,"rejected","Invalid close list or trading disabled"); return; }
 // Validate the entire list before any close. Never fall back to closing by symbol.
 for(int i=0;i<count;i++) {
  ulong ticket=(ulong)StringToInteger(items[i]);
  if(ticket==0) { Ack(id,"rejected","Invalid close ticket"); return; }
  if(!PositionSelectByTicket(ticket)) continue;
  if((ulong)PositionGetInteger(POSITION_MAGIC)!=MAGIC || PositionGetString(POSITION_SYMBOL)!=_Symbol) { Ack(id,"rejected","Close ticket ownership mismatch"); return; }
 }
 bool complete=true;
 for(int i=0;i<count;i++) {
  ulong ticket=(ulong)StringToInteger(items[i]);
  if(!PositionSelectByTicket(ticket)) continue;
  if(!trade.PositionClose(ticket,20)) complete=false;
  if(PositionSelectByTicket(ticket)) complete=false;
 }
 Ack(id,complete ? "closed":"pending",complete ? "Selected positions closed":"Close not complete; inspect positions");
}
void CloseOwn() {
 if(!CanTrade()) { last_note="Stop requested; closing waits for connection and Algo Trading"; return; }
 for(int i=PositionsTotal()-1;i>=0;i--) {
  ulong ticket=PositionGetTicket(i);
  if(ticket>0 && (ulong)PositionGetInteger(POSITION_MAGIC)==MAGIC) {
   bool ok=trade.PositionClose(ticket,20);
   uint rc=trade.ResultRetcode();
   if(!ok || (rc!=TRADE_RETCODE_DONE && rc!=TRADE_RETCODE_DONE_PARTIAL)) last_note="Close pending/failed: "+trade.ResultRetcodeDescription();
  }
 }
}
string ManagementKey(long identifier) { return risk_key+"M_"+(string)identifier+"_"; }
// Recover original fill/SL/volume from broker history, never from a trailed SL.
bool InitialPosition(ulong ticket,double &entry,double &distance,double &original) {
 if(!PositionSelectByTicket(ticket)) return false;
 long identifier=PositionGetInteger(POSITION_IDENTIFIER);
 if(!HistorySelectByPosition(identifier)) return false;
 bool found=false; original=0;
 for(int j=0;j<HistoryDealsTotal();j++) {
  ulong deal=HistoryDealGetTicket(j);
  if(HistoryDealGetInteger(deal,DEAL_ENTRY)!=DEAL_ENTRY_IN) continue;
  if((ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=MAGIC || HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol) return false;
  double price=HistoryDealGetDouble(deal,DEAL_PRICE),sl=HistoryDealGetDouble(deal,DEAL_SL);
  if(price<=0 || sl<=0 || MathAbs(price-sl)<=0) return false;
  if(found) return false; // Netting additions/reversals are not a supported managed entry.
  entry=price; distance=MathAbs(price-sl); original=HistoryDealGetDouble(deal,DEAL_VOLUME); found=true;
 }
 return found && PositionSelectByTicket(ticket);
}
void StoreManagement(ulong deal,int profile,long expiry) {
 if(deal==0 || !HistoryDealSelect(deal)) return;
 string prefix=ManagementKey(HistoryDealGetInteger(deal,DEAL_POSITION_ID));
 GlobalVariableSet(prefix+"profile",profile); GlobalVariableSet(prefix+"expiry",(double)expiry);
 GlobalVariablesFlush();
}
void ManagePositions() {
 if(!CanTrade()) return;
 MqlTick tick; if(!SymbolInfoTick(_Symbol,tick) || tick.bid<=0 || tick.ask<tick.bid
                 || TimeTradeServer()<tick.time || TimeTradeServer()-tick.time>5) return;
 double ts=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),point=SymbolInfoDouble(_Symbol,SYMBOL_POINT);
 if(ts<=0 || point<=0) return;
 for(int i=PositionsTotal()-1;i>=0;i--) {
  ulong ticket=PositionGetTicket(i);
  if(ticket==0 || (ulong)PositionGetInteger(POSITION_MAGIC)!=MAGIC || PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
  double entry=0,dist=0,original=0;
  if(!InitialPosition(ticket,entry,dist,original)) continue;
  long identifier=PositionGetInteger(POSITION_IDENTIFIER);
  string prefix=ManagementKey(identifier);
  bool buy=PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY;
  int side=buy ? 1:-1;
  double price=buy ? tick.bid:tick.ask,volume=PositionGetDouble(POSITION_VOLUME);
  double progress=side*(price-entry)/dist;
  bool strong=GlobalVariableCheck(prefix+"profile") && GlobalVariableGet(prefix+"profile")==1
              && GlobalVariableGet(prefix+"expiry")>(double)TimeGMT();
  bool consumed=GlobalVariableCheck(prefix+"partial") || volume<original-SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP)*.1;
  double initial_loss=0;
  if(!OrderCalcProfit(buy ? ORDER_TYPE_BUY:ORDER_TYPE_SELL,_Symbol,original,entry,entry-side*dist,initial_loss)) continue;
  double net=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP);
  // Buffer is not a guarantee against broker fees or execution slippage.
  int action=ManagedExitAction(progress,strong,consumed,net,MathMax(.01,MathAbs(initial_loss)*.10));
  if(action>0 && (!GlobalVariableCheck(prefix+"try") || TimeGMT()-GlobalVariableGet(prefix+"try")>=5)) {
   GlobalVariableSet(prefix+"try",(double)TimeGMT());
   if(action==2) {
    double amount=ManagedPartialVolume(original,volume,SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP));
    // Consume before submitting: timeout/crash cannot cause a second half-close.
    GlobalVariableSet(prefix+"partial",1); GlobalVariablesFlush();
    if(amount>0 && AccountInfoInteger(ACCOUNT_MARGIN_MODE)==ACCOUNT_MARGIN_MODE_RETAIL_HEDGING) {
     bool ok=trade.PositionClosePartial(ticket,NormalizeDouble(amount,8),20);
     last_note="Staged profit: "+(ok ? "partial request: ":"partial failed: ")+trade.ResultRetcodeDescription();
    } else {
     trade.PositionClose(ticket,20); last_note="Staged profit: indivisible/netting position full-exit request: "+trade.ResultRetcodeDescription();
    }
   } else {
    trade.PositionClose(ticket,20); last_note="Managed profit full-exit request: "+trade.ResultRetcodeDescription();
   }
  }
  if(progress<1. || !PositionSelectByTicket(ticket)) continue;
  // At 1R, protect the entry; then trail by 0.5R. Never widen the existing SL.
  double minimum=(double)MathMax(SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL),SymbolInfoInteger(_Symbol,SYMBOL_TRADE_FREEZE_LEVEL))*point+ts;
  double old=PositionGetDouble(POSITION_SL);
  double wanted=NormalizeDouble(ManagedStop(side,entry,price,dist,old,ts,minimum),_Digits);
  if(wanted<=0) continue;
  if(GlobalVariableCheck(prefix+"modify") && TimeGMT()-GlobalVariableGet(prefix+"modify")<5) continue;
  GlobalVariableSet(prefix+"modify",(double)TimeGMT());
  bool modified=trade.PositionModify(ticket,wanted,PositionGetDouble(POSITION_TP));
  if(!modified || (trade.ResultRetcode()!=TRADE_RETCODE_DONE && trade.ResultRetcode()!=TRADE_RETCODE_NO_CHANGES)) last_note="Trailing SL pending: "+trade.ResultRetcodeDescription();
 }
}
void RiskGuard() {
 double eq=AccountInfoDouble(ACCOUNT_EQUITY);
 if(eq<=0) { halted=true; return; }
 string peak=risk_key+"peak";
 if(!GlobalVariableCheck(peak)) GlobalVariableSet(peak,eq);
 if(eq>GlobalVariableGet(peak)) GlobalVariableSet(peak,eq);
 string day=TimeToString(TimeGMT(),TIME_DATE); string daily=risk_key+day;
 if(!GlobalVariableCheck(daily)) GlobalVariableSet(daily,eq);
 halted=(eq<=GlobalVariableGet(peak)*(1-control_drawdown) || eq<=GlobalVariableGet(daily)*(1-control_daily));
 if(halted) { WriteFile(BASE+"stop.flag","Risk limit reached"); last_note="Stopped: daily 2% or peak drawdown 10% limit"; }
}
bool IdentifierOpen(long identifier) {
 for(int i=0;i<PositionsTotal();i++) if(PositionGetTicket(i)>0 && PositionGetInteger(POSITION_IDENTIFIER)==identifier) return true;
 return false;
}
long EntryGuard() {
 if(control_cooldown==0 && !control_cluster) return 0;
 long now=(long)TimeTradeServer(),period=PeriodSeconds(_Period);
 if(!HistorySelect(now-90*86400,now)) return -1;
 long ids[],closed[]; double incoming[],outgoing[],nets[]; bool stopped[],bad[]; string symbols[];
 int count=0;
 for(int i=0;i<HistoryDealsTotal();i++) {
  ulong ticket=HistoryDealGetTicket(i);
  if(ticket==0 || !PortfolioMagic(HistoryDealGetInteger(ticket,DEAL_MAGIC))) continue;
  long kind=HistoryDealGetInteger(ticket,DEAL_TYPE);
  if(kind!=DEAL_TYPE_BUY && kind!=DEAL_TYPE_SELL) continue;
  long identifier=HistoryDealGetInteger(ticket,DEAL_POSITION_ID);
  if(identifier<=0) continue;
  int at=-1;
  for(int j=0;j<count;j++) if(ids[j]==identifier) { at=j; break; }
  if(at<0) {
   at=count++; ArrayResize(ids,count); ArrayResize(closed,count); ArrayResize(incoming,count); ArrayResize(outgoing,count);
   ArrayResize(nets,count); ArrayResize(stopped,count); ArrayResize(bad,count); ArrayResize(symbols,count);
   ids[at]=identifier; closed[at]=0; incoming[at]=0; outgoing[at]=0; nets[at]=0; stopped[at]=false; bad[at]=false;
   symbols[at]=HistoryDealGetString(ticket,DEAL_SYMBOL);
  }
  long entry=HistoryDealGetInteger(ticket,DEAL_ENTRY);
  double volume=HistoryDealGetDouble(ticket,DEAL_VOLUME);
  if(entry==DEAL_ENTRY_IN) incoming[at]+=volume;
  else if(entry==DEAL_ENTRY_OUT || entry==DEAL_ENTRY_OUT_BY) {
   outgoing[at]+=volume;
   closed[at]=(long)MathMax(closed[at],HistoryDealGetInteger(ticket,DEAL_TIME));
   if(HistoryDealGetInteger(ticket,DEAL_REASON)==DEAL_REASON_SL) stopped[at]=true;
  } else bad[at]=true;
  nets[at]+=HistoryDealGetDouble(ticket,DEAL_PROFIT)+HistoryDealGetDouble(ticket,DEAL_COMMISSION)+HistoryDealGetDouble(ticket,DEAL_SWAP)+HistoryDealGetDouble(ticket,DEAL_FEE);
 }
 long last_exit=0,last_stop=0,last_global_stop=0; int stops=0,global_stops=0;
 for(int i=0;i<count;i++) {
  if(bad[i] || incoming[i]<=0 || MathAbs(incoming[i]-outgoing[i])>0.00000001 || IdentifierOpen(ids[i]) || closed[i]>now) continue;
  if(symbols[i]==_Symbol && closed[i]>last_exit) last_exit=closed[i];
  if(stopped[i] && nets[i]<0 && closed[i]>=now-control_window*period) {
   global_stops++; if(closed[i]>last_global_stop) last_global_stop=closed[i];
   if(symbols[i]==_Symbol) { stops++; if(closed[i]>last_stop) last_stop=closed[i]; }
  }
 }
 return EntryPauseUntil(now,period,last_exit,stops,last_stop,global_stops,last_global_stop,
     control_cooldown,control_cluster,control_lock,control_symbol_stops,control_account_stops);
}
bool Lease(string &token) {
 int h=FileOpen(BASE+"lease.tsv",FILE_READ|FILE_CSV|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE,'\t',CP_UTF8);
 if(h==INVALID_HANDLE) return false;
 long stamp=(long)StringToInteger(FileReadString(h));
 long login=(long)StringToInteger(FileReadString(h)); token=FileReadString(h);
 string sym=FileReadString(h); int period=(int)StringToInteger(FileReadString(h));
 string instance=FileReadString(h); FileClose(h);
 long age=(long)TimeGMT()-stamp;
 return age>=-5 && age<=30 && login==AccountInfoInteger(ACCOUNT_LOGIN) && sym==_Symbol && period==(int)_Period && StringLen(token)==32 && instance==executor_instance;
}
bool ProtectedOwnPositions() {
 for(int i=PositionsTotal()-1;i>=0;i--) {
  if(PositionGetTicket(i)==0 || (ulong)PositionGetInteger(POSITION_MAGIC)!=MAGIC) continue;
  if(PositionGetString(POSITION_SYMBOL)!=_Symbol || PositionGetDouble(POSITION_SL)<=0 || PositionGetDouble(POSITION_TP)<=0) return false;
 }
 return true;
}
void Ack(long id,string status,string note,ulong order=0,ulong deal=0) {
 WriteFile(BASE+"ack.json","{\"id\":"+(string)id+",\"status\":"+Q(status)+",\"note\":"+Q(note)+",\"order\":"+(string)order+",\"deal\":"+(string)deal+",\"utc\":"+(string)(long)TimeGMT()+"}"); last_note=note;
}
string EntryRiskFile(ulong ticket) { return BASE+"entry_risk_"+(string)initial_login+"_"+(string)ticket+".json"; }
void OnTradeTransaction(const MqlTradeTransaction &transaction,const MqlTradeRequest &request,const MqlTradeResult &result) {
 if(!Demo() || AccountInfoInteger(ACCOUNT_LOGIN)!=initial_login || transaction.type!=TRADE_TRANSACTION_DEAL_ADD) return;
 ulong ticket=transaction.deal;
 if(ticket==0 || !HistoryDealSelect(ticket)) return;
 if((ulong)HistoryDealGetInteger(ticket,DEAL_MAGIC)!=MAGIC || HistoryDealGetString(ticket,DEAL_SYMBOL)!=_Symbol || HistoryDealGetInteger(ticket,DEAL_ENTRY)!=DEAL_ENTRY_IN) return;
 if(FileIsExist(EntryRiskFile(ticket))) return;
 long type=HistoryDealGetInteger(ticket,DEAL_TYPE);
 if(type!=DEAL_TYPE_BUY && type!=DEAL_TYPE_SELL) return;
 double price=HistoryDealGetDouble(ticket,DEAL_PRICE),sl=HistoryDealGetDouble(ticket,DEAL_SL),loss=0;
 double volume=HistoryDealGetDouble(ticket,DEAL_VOLUME);
 long lag=(long)TimeTradeServer()-(long)HistoryDealGetInteger(ticket,DEAL_TIME);
 if(lag< -5 || lag>60) return;
 if(sl<=0 || volume<=0 || !OrderCalcProfit(type==DEAL_TYPE_BUY ? ORDER_TYPE_BUY:ORDER_TYPE_SELL,_Symbol,volume,price,sl,loss) || !MathIsValidNumber(loss) || loss>=0) return;
 // Capture once at entry. Later currency conversion is never substituted for initial risk.
 string record="{\"method\":\"entry_fill_sl_estimate\",\"login\":"+(string)initial_login+",\"symbol\":"+Q(_Symbol)+
 ",\"deal\":"+(string)ticket+",\"order\":"+(string)HistoryDealGetInteger(ticket,DEAL_ORDER)+",\"position_id\":"+(string)HistoryDealGetInteger(ticket,DEAL_POSITION_ID)+
 ",\"entry_time\":"+(string)HistoryDealGetInteger(ticket,DEAL_TIME)+",\"capture_lag_seconds\":"+(string)lag+",\"captured_utc\":"+(string)(long)TimeGMT()+",\"cash\":"+DoubleToString(-loss,8)+
 ",\"currency\":"+Q(AccountInfoString(ACCOUNT_CURRENCY))+",\"price\":"+DoubleToString(price,_Digits)+",\"sl\":"+DoubleToString(sl,_Digits)+",\"volume\":"+DoubleToString(volume,8)+"}";
 WriteFile(EntryRiskFile(ticket),record);
}
string EntryRisk(ulong ticket) {
 static ulong tickets[]; static string records[];
 for(int i=0;i<ArraySize(tickets);i++) if(tickets[i]==ticket) return records[i];
 int h=FileOpen(EntryRiskFile(ticket),FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ,0,CP_UTF8);
 if(h==INVALID_HANDLE) return "null";
 string record=FileReadString(h); FileClose(h);
 if(StringLen(record)==0) return "null";
 int n=ArraySize(tickets); ArrayResize(tickets,n+1); ArrayResize(records,n+1); tickets[n]=ticket; records[n]=record;
 return record;
}
void ProcessRequest(string token) {
 int h=FileOpen(BASE+"request.tsv",FILE_READ|FILE_CSV|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE,'\t',CP_UTF8);
 if(h==INVALID_HANDLE) return;
 long id=StringToInteger(FileReadString(h)); long expiry=StringToInteger(FileReadString(h));
 long login=StringToInteger(FileReadString(h)); string session=FileReadString(h); string action=FileReadString(h);
 string symbol=FileReadString(h); int direction=(int)StringToInteger(FileReadString(h));
 double dist=StringToDouble(FileReadString(h)); double reward=StringToDouble(FileReadString(h));
 long bar=StringToInteger(FileReadString(h)); string strat=FileReadString(h); string tickets=FileReadString(h);
 double requested_fraction=0,symbol_cap=0;
 if(!FileIsEnding(h)) requested_fraction=StringToDouble(FileReadString(h));
 if(!FileIsEnding(h)) symbol_cap=StringToDouble(FileReadString(h));
 int profile=-1; long thesis_expiry=0;
 if(!FileIsEnding(h)) profile=(int)StringToInteger(FileReadString(h));
 if(!FileIsEnding(h)) thesis_expiry=StringToInteger(FileReadString(h));
 FileClose(h);
 if(id<=0 || id<=(long)GlobalVariableGet(key+"last_request")) return;
 // Persist consumption BEFORE broker call: an uncertain request is never replayed after a crash.
 GlobalVariableSet(key+"last_request",(double)id); GlobalVariablesFlush();
 if(!Demo() || session!=token || login!=AccountInfoInteger(ACCOUNT_LOGIN) || symbol!=_Symbol || expiry<(long)TimeGMT() || expiry>(long)TimeGMT()+60) { Ack(id,"rejected","Account/session/expiry mismatch"); return; }
 if(action=="close_tickets") { CloseSelected(id,tickets); return; }
 if(action=="close") { CloseOwn(); Ack(id,OwnCount()==0 ? "closed":"pending",last_note); return; }
 if(action!="open" || halted || FileIsExist(BASE+"stop.flag") || !CanTrade()) { Ack(id,"rejected","Trading disabled or halted"); return; }
 UpdateWeeklySchedule();
 if(weekly_state!=0 || weekly_liquidation_pending) { Ack(id,"rejected",weekly_state==1 || weekly_liquidation_pending ? "Weekly close: entries paused":"Trading session schedule unavailable; entries paused"); return; }
 if(direction!=1 && direction!=-1) { Ack(id,"rejected","Invalid direction"); return; }
 if((profile!=0 && profile!=1) || requested_fraction>.0025 || (profile==0 && thesis_expiry!=0)
    || (profile==1 && (thesis_expiry<(long)TimeGMT()+30 || thesis_expiry>(long)TimeGMT()+1800))) { Ack(id,"rejected","Invalid managed exit profile or sizing"); return; }
 if(!MathIsValidNumber(dist) || !MathIsValidNumber(reward) || dist<=0 || reward<=0 || reward>dist*3) { Ack(id,"rejected","Invalid SL/TP"); return; }
 if(MathAbs(reward/dist-(profile==1 ? 2.:1.))>.000001) { Ack(id,"rejected","Managed target mismatch"); return; }
 if(TimeTradeServer()<iTime(_Symbol,_Period,0) || TimeTradeServer()-iTime(_Symbol,_Period,0)>EntryWindow()) { Ack(id,"rejected","Signal window closed; wait for next new bar"); return; }
 if(bar!=(long)iTime(_Symbol,_Period,1) || bar<=(long)GlobalVariableGet(key+"last_bar")) { Ack(id,"rejected","Stale/duplicate signal bar"); return; }
 // Never mix robot exposure with manual/other EA positions or pending orders.
 if(OwnCount()>=PositionLimit() || BlockingPositions()>0 || OrdersTotal()>0) { Ack(id,"rejected","Existing exposure blocks this symbol"); return; }
 long pause_until=EntryGuard();
 if(pause_until!=0) { Ack(id,"rejected",pause_until<0 ? "Entry protection history unavailable":"Entry cooldown/stop-loss cluster pause until "+TimeToString((datetime)pause_until)); return; }
 MqlTick tick; if(!SymbolInfoTick(_Symbol,tick) || tick.bid<=0 || tick.ask<tick.bid || TimeTradeServer()-tick.time>120 || TimeTradeServer()<tick.time) { Ack(id,"rejected","Missing/stale quote"); return; }
 double point=SymbolInfoDouble(_Symbol,SYMBOL_POINT), ts=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
 if(ts<=0 || point<=0 || (tick.ask-tick.bid)>dist*control_spread) { Ack(id,"rejected","Spread too large"); return; }
 double price=(direction>0 ? tick.ask:tick.bid);
 double sl=NormalizeDouble((direction>0 ? MathFloor((price-dist)/ts):MathCeil((price+dist)/ts))*ts,_Digits);
 double tp=NormalizeDouble((direction>0 ? MathCeil((price+reward)/ts):MathFloor((price-reward)/ts))*ts,_Digits);
 double minstop=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*point;
 if((direction>0 ? tick.bid-sl:sl-tick.ask)<minstop || (direction>0 ? tp-tick.bid:tick.ask-tp)<minstop) { Ack(id,"rejected","Broker stop distance"); return; }
 ENUM_ORDER_TYPE type=(direction>0 ? ORDER_TYPE_BUY:ORDER_TYPE_SELL);
 double loss=0,minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
 if(step<=0 || minimum<=0 || !OrderCalcProfit(type,_Symbol,minimum,price,sl,loss) || loss>=0) { Ack(id,"rejected","Cannot calculate risk"); return; }
 // Nominal SL risk: each entry, symbol and whole portfolio <=0.5%.
 // Fees, execution slippage and gaps are not guaranteed by this estimate.
 AllocationLock allocation_lock;
 if(!allocation_lock.Acquire(risk_key+"allocation_lock")) { Ack(id,"rejected","Portfolio allocation busy; no order sent"); return; }
 double used=OwnRisk(direction),equity=AccountInfoDouble(ACCOUNT_EQUITY);
 if(used<0 || equity<=0) { Ack(id,"rejected","Opposite exposure or missing risk data"); return; }
 int usd_side=(_Symbol=="USDJPY" ? 1:-1)*direction;
 double budget=AllocationBudget(equity,requested_fraction,symbol_cap,used,PortfolioRisk(),PortfolioRisk(usd_side),control_gross_cap);
 if(budget<=0) { Ack(id,"rejected","Symbol risk budget exhausted"); return; }
 double volume=MathFloor((budget/(-loss/minimum))/step)*step;
 volume=NormalizeDouble(MathMin(volume,SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX)),8);
 double actual_loss=0;
 if(volume<minimum || !OrderCalcProfit(type,_Symbol,volume,price,sl,actual_loss) || !MathIsValidNumber(actual_loss) || -actual_loss>budget+.000001) { Ack(id,"rejected","Risk/lot minimum limit"); return; }
 double margin=0;
 if(volume<minimum || !OrderCalcMargin(type,_Symbol,volume,price,margin) || margin+AccountInfoDouble(ACCOUNT_MARGIN)>AccountInfoDouble(ACCOUNT_EQUITY)*control_margin) { Ack(id,"rejected","Volume/minimum/margin limit"); return; }
 GlobalVariableSet(key+"last_bar",(double)bar); GlobalVariablesFlush();
 trade.SetTypeFillingBySymbol(_Symbol);
 string comment="KH:"+StringSubstr(strat,0,25);
 bool sent=(direction>0 ? trade.Buy(volume,_Symbol,0,sl,tp,comment):trade.Sell(volume,_Symbol,0,sl,tp,comment));
 uint ret=trade.ResultRetcode();
 if(sent && (ret==TRADE_RETCODE_DONE || ret==TRADE_RETCODE_DONE_PARTIAL)) StoreManagement(trade.ResultDeal(),profile,thesis_expiry);
 Ack(id,(sent && (ret==TRADE_RETCODE_DONE || ret==TRADE_RETCODE_DONE_PARTIAL)) ? "executed":"not_confirmed",trade.ResultRetcodeDescription(),trade.ResultOrder(),trade.ResultDeal());
}
void Publish() {
 bool demo=Demo(); MqlTick tick; ZeroMemory(tick); SymbolInfoTick(_Symbol,tick);
 string s="{\"executor_version\":9,\"ea_version\":\"3.51\",\"controls_revision\":"+Q(controls_revision)+",\"cooldown_bars\":"+(string)control_cooldown+",\"stop_cluster_enabled\":"+B(control_cluster)+",\"exit_policy_version\":2,\"adaptive_risk_schema\":1,\"risk_policy_version\":2,\"trade_memory_schema\":1,\"executor_instance\":"+Q(executor_instance)+",\"schema\":2,\"demo\":"+B(demo)+",\"connected\":"+B((bool)TerminalInfoInteger(TERMINAL_CONNECTED))+
 ",\"generated_utc\":"+(string)(long)TimeGMT()+",\"algo_enabled\":"+B(CanTrade())+",\"halted\":"+B(halted)+",\"stopped\":"+B(FileIsExist(BASE+"stop.flag"))+
 ",\"note\":"+Q(last_note)+",\"symbol\":"+Q(_Symbol)+",\"period\":"+(string)(int)_Period+",\"period_seconds\":"+(string)PeriodSeconds(_Period);
 s+=",\"max_positions\":"+(string)PositionLimit()+",\"entry_window_seconds\":"+(string)EntryWindow()+",\"bar_age_seconds\":"+(string)(long)(TimeTradeServer()-iTime(_Symbol,_Period,0));
 s+=",\"broker_utc_offset_seconds\":"+(string)((long)TimeTradeServer()-(long)TimeGMT());
 s+=",\"weekly_schedule_known\":"+B(weekly_state>=0)+",\"weekly_close_paused\":"+B(weekly_state==1 || weekly_liquidation_pending)+",\"weekly_close_server\":"+(string)weekly_close_at+",\"weekly_reopen_server\":"+(string)weekly_open_at;
 if(demo) {
  s+=",\"login\":"+(string)AccountInfoInteger(ACCOUNT_LOGIN)+",\"currency\":"+Q(AccountInfoString(ACCOUNT_CURRENCY))+
  ",\"balance\":"+DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE),2)+",\"equity\":"+DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2)+
  ",\"point\":"+DoubleToString(_Point,10)+",\"bid\":"+DoubleToString(tick.bid,_Digits)+",\"ask\":"+DoubleToString(tick.ask,_Digits)+
  ",\"tick_age_seconds\":"+(string)(long)(TimeTradeServer()-tick.time)+",\"own_positions\":"+(string)OwnCount()+",\"blocking_positions\":"+(string)BlockingPositions()+",\"total_positions\":"+(string)PositionsTotal()+",\"total_orders\":"+(string)OrdersTotal();
  s+=",\"positions\":["; int added=0;
  for(int i=0;i<PositionsTotal();i++) {
   ulong ticket=PositionGetTicket(i); if(ticket==0 || (ulong)PositionGetInteger(POSITION_MAGIC)!=MAGIC) continue;
   if(added++>0) s+=",";
   double risk_loss=0,sl=PositionGetDouble(POSITION_SL);
   double initial_entry=0,initial_distance=0,initial_volume=0;
   bool managed_known=InitialPosition(ticket,initial_entry,initial_distance,initial_volume);
   if(!PositionSelectByTicket(ticket)) continue;
   bool risk_known=sl>0 && OrderCalcProfit(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? ORDER_TYPE_BUY:ORDER_TYPE_SELL,_Symbol,PositionGetDouble(POSITION_VOLUME),PositionGetDouble(POSITION_PRICE_OPEN),sl,risk_loss) && MathIsValidNumber(risk_loss);
   s+="{\"identifier\":"+(string)PositionGetInteger(POSITION_IDENTIFIER)+",\"ticket\":"+(string)ticket+",\"direction\":"+(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? "1":"-1")+
   ",\"sl_risk_cash\":"+(risk_known ? DoubleToString(MathMax(0,-risk_loss),8):"null")+
   ",\"progress_r\":"+(managed_known ? DoubleToString((PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? 1:-1)*((PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? tick.bid:tick.ask)-initial_entry)/initial_distance,8):"null")+
   ",\"bars_held\":"+(string)iBarShift(_Symbol,_Period,(datetime)PositionGetInteger(POSITION_TIME),false)+
   ",\"profit\":"+DoubleToString(PositionGetDouble(POSITION_PROFIT),2)+",\"swap\":"+DoubleToString(PositionGetDouble(POSITION_SWAP),8)+",\"volume\":"+DoubleToString(PositionGetDouble(POSITION_VOLUME),8)+",\"comment\":"+Q(PositionGetString(POSITION_COMMENT))+"}";
  }
  static string cached_bars=""; static datetime cached_bar=0;
  datetime latest_bar=iTime(_Symbol,_Period,1);
  if(cached_bars=="" || latest_bar!=cached_bar) {
  cached_bars="],\"bars\":["; MqlRates rates[]; ArraySetAsSeries(rates,false); int n=CopyRates(_Symbol,_Period,1,2000,rates);
  for(int i=0;i<n;i++) {
   if(i>0) cached_bars+=",";
   cached_bars+="{\"time\":"+(string)(long)rates[i].time+",\"open\":"+DoubleToString(rates[i].open,_Digits)+",\"high\":"+DoubleToString(rates[i].high,_Digits)+
   ",\"low\":"+DoubleToString(rates[i].low,_Digits)+",\"close\":"+DoubleToString(rates[i].close,_Digits)+",\"spread\":"+(string)rates[i].spread+"}";
  }

   if(n>=1000) cached_bar=latest_bar;
  }
  s+=cached_bars;
  s+="],\"deals\":["; added=0;
  if(HistorySelect(TimeCurrent()-90*86400,TimeCurrent())) {
   int total=HistoryDealsTotal();
   for(int i=MathMax(0,total-2000);i<total;i++) {
    ulong t=HistoryDealGetTicket(i); if(t==0 || (ulong)HistoryDealGetInteger(t,DEAL_MAGIC)!=MAGIC) continue;
    if(added++>0) s+=",";
    double net=HistoryDealGetDouble(t,DEAL_PROFIT)+HistoryDealGetDouble(t,DEAL_COMMISSION)+HistoryDealGetDouble(t,DEAL_SWAP)+HistoryDealGetDouble(t,DEAL_FEE);
    s+="{\"ticket\":"+(string)t+",\"position_id\":"+(string)HistoryDealGetInteger(t,DEAL_POSITION_ID)+",\"entry\":"+(string)HistoryDealGetInteger(t,DEAL_ENTRY)+
    ",\"time\":"+(string)HistoryDealGetInteger(t,DEAL_TIME)+",\"order\":"+(string)HistoryDealGetInteger(t,DEAL_ORDER)+",\"reason\":"+(string)HistoryDealGetInteger(t,DEAL_REASON)+
    ",\"volume\":"+DoubleToString(HistoryDealGetDouble(t,DEAL_VOLUME),8)+",\"price\":"+DoubleToString(HistoryDealGetDouble(t,DEAL_PRICE),_Digits)+
    ",\"profit\":"+DoubleToString(HistoryDealGetDouble(t,DEAL_PROFIT),8)+",\"commission\":"+DoubleToString(HistoryDealGetDouble(t,DEAL_COMMISSION),8)+
    ",\"swap\":"+DoubleToString(HistoryDealGetDouble(t,DEAL_SWAP),8)+",\"fee\":"+DoubleToString(HistoryDealGetDouble(t,DEAL_FEE),8)+
    ",\"initial_risk\":"+(HistoryDealGetInteger(t,DEAL_ENTRY)==DEAL_ENTRY_IN ? EntryRisk(t):"null")+
    ",\"net\":"+DoubleToString(net,2)+",\"comment\":"+Q(HistoryDealGetString(t,DEAL_COMMENT))+"}";
   }
  }
  s+="]";
 }
 s+="}"; WriteFile(BASE+"snapshot.json",s);
}
int OnInit() {
 if(!Demo()) { Print("Khorshid accepts DEMO accounts only"); return INIT_FAILED; }
 int slot=0;
 if(_Symbol=="XAUUSD") slot=1;
 else if(_Symbol=="EURUSD") slot=2;
 else if(_Symbol=="USDJPY") slot=4;
 if(slot==0) { Print("Supported exact symbols: XAUUSD, EURUSD, USDJPY"); return INIT_FAILED; }
 MAGIC=(ulong)(260100930+slot);
 FolderCreate("khorshid_multi"); FolderCreate("khorshid_multi\\"+_Symbol);
 BASE="khorshid_multi\\"+_Symbol+"\\khorshid_demo_";
 owner_key="KHM3_"+_Symbol+"_";
 risk_key="KHDEMO_"+(string)AccountInfoInteger(ACCOUNT_LOGIN)+"_";
 if(GlobalVariableCheck(owner_key+"time") && TimeGMT()-GlobalVariableGet(owner_key+"time")<10 && GlobalVariableGet(owner_key+"chart")!=(double)ChartID()
    && ChartSymbol((long)GlobalVariableGet(owner_key+"chart"))==_Symbol) { Print("Attach only ONE KhorshidMultiTrader per symbol"); return INIT_FAILED; }
 owns=true; initial_login=AccountInfoInteger(ACCOUNT_LOGIN);
 startup_started=GetTickCount64(); startup_reconciled=false;
 executor_instance=(string)(long)TimeGMT()+"-"+(string)startup_started+"-"+(string)ChartID();
 // An order queued before terminal shutdown is never replayed on restart.
 FileDelete(BASE+"request.tsv");
 GlobalVariableSet(owner_key+"chart",(double)ChartID()); GlobalVariableSet(owner_key+"time",(double)TimeGMT());
 key="KHM3_"+(string)AccountInfoInteger(ACCOUNT_LOGIN)+"_"+_Symbol+"_";
 weekly_liquidation_pending=GlobalVariableCheck(key+"weekly_close_pending");
 if(!GlobalVariableCheck(key+"last_request")) GlobalVariableSet(key+"last_request",0);
 if(!GlobalVariableCheck(key+"last_bar")) GlobalVariableSet(key+"last_bar",0);
 trade.SetExpertMagicNumber(MAGIC); trade.SetAsyncMode(false); trade.SetDeviationInPoints(20);
 if(!EventSetTimer(1)) return INIT_FAILED;
 UpdateWeeklySchedule(); Publish(); return INIT_SUCCEEDED;
}
void OnTimer() {
 LoadControls();
 if(!Demo() || AccountInfoInteger(ACCOUNT_LOGIN)!=initial_login) { halted=true; last_note="Blocked: account is no longer DEMO"; Publish(); return; }
 GlobalVariableSet(owner_key+"time",(double)TimeGMT());
 RiskGuard(); UpdateWeeklySchedule(); string token;
 bool pending=WeeklyExitPending(weekly_liquidation_pending,weekly_state,(bool)TerminalInfoInteger(TERMINAL_CONNECTED),OwnCount());
 if(pending!=weekly_liquidation_pending) {
  weekly_liquidation_pending=pending;
  if(pending) GlobalVariableSet(key+"weekly_close_pending",(double)TimeTradeServer());
  else GlobalVariableDel(key+"weekly_close_pending");
  GlobalVariablesFlush();
 }
 bool active_lease=Lease(token);
 int recovery_action=RestartPolicy(halted || FileIsExist(BASE+"stop.flag"),active_lease,startup_reconciled,
                                   (long)(GetTickCount64()-startup_started),ProtectedOwnPositions());
 if(recovery_action==2) { if(OwnCount()>0) CloseOwn(); }
 else if(weekly_state==1 || weekly_liquidation_pending) {
  if(active_lease) startup_reconciled=true;
  // Never clear a manual/risk stop, and never replay an entry queued on Friday.
  FileDelete(BASE+"request.tsv");
  last_note="Weekly close: entries paused; closing robot positions";
  ulong elapsed=GetTickCount64();
  if(OwnCount()>0 && (weekly_last_close_try==0 || elapsed-weekly_last_close_try>=5000)) {
   weekly_last_close_try=elapsed; CloseOwn();
  }
  if(OwnCount()==0) last_note="Weekly close: robot positions flat; waiting for reopening";
 }
 else if(recovery_action==1) { startup_reconciled=true; ManagePositions(); ProcessRequest(token); }
 else {
  // Bounded startup handover only. Existing broker SL/TP remain untouched;
  // no new order is accepted before the worker acknowledges this instance.
  last_note="Restart: waiting for worker reconciliation (maximum 15 seconds)";
 }
 Publish();
}
void OnDeinit(const int reason) {
 EventKillTimer();
 if(!owns) return;
 if(GlobalVariableGet(owner_key+"chart")== (double)ChartID()) GlobalVariableDel(owner_key+"time");
 FileDelete(BASE+"snapshot.json");
}
