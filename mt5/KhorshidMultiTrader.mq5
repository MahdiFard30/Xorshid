#property strict
#property version "3.23"
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
void UpdateWeeklySchedule() {
 datetime now=TimeTradeServer();
 if(weekly_checked>0 && now>=weekly_checked && now-weekly_checked<60) {
  if(weekly_close_at>0) weekly_state=((long)now>=weekly_close_at-600 && (long)now<weekly_open_at) ? 1:0;
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
 weekly_state=WeeklyClosePolicy((long)now,starts,ends,count,weekly_close_at,weekly_open_at);
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
int PositionLimit() { return AccountInfoInteger(ACCOUNT_MARGIN_MODE)==ACCOUNT_MARGIN_MODE_RETAIL_HEDGING ? 2:1; }
int EntryWindow() { return (int)MathMin(300,MathMax(1,PeriodSeconds(_Period)/2)); }
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
void RiskGuard() {
 double eq=AccountInfoDouble(ACCOUNT_EQUITY);
 if(eq<=0) { halted=true; return; }
 string peak=risk_key+"peak";
 if(!GlobalVariableCheck(peak)) GlobalVariableSet(peak,eq);
 if(eq>GlobalVariableGet(peak)) GlobalVariableSet(peak,eq);
 string day=TimeToString(TimeGMT(),TIME_DATE); string daily=risk_key+day;
 if(!GlobalVariableCheck(daily)) GlobalVariableSet(daily,eq);
 halted=(eq<=GlobalVariableGet(peak)*.90 || eq<=GlobalVariableGet(daily)*.98);
 if(halted) { WriteFile(BASE+"stop.flag","Risk limit reached"); last_note="Stopped: daily 2% or peak drawdown 10% limit"; }
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
 long bar=StringToInteger(FileReadString(h)); string strat=FileReadString(h); string tickets=FileReadString(h); FileClose(h);
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
 if(!MathIsValidNumber(dist) || !MathIsValidNumber(reward) || dist<=0 || reward<=0 || reward>dist*3) { Ack(id,"rejected","Invalid SL/TP"); return; }
 if(TimeTradeServer()<iTime(_Symbol,_Period,0) || TimeTradeServer()-iTime(_Symbol,_Period,0)>EntryWindow()) { Ack(id,"rejected","Signal window closed; wait for next new bar"); return; }
 if(bar!=(long)iTime(_Symbol,_Period,1) || bar<=(long)GlobalVariableGet(key+"last_bar")) { Ack(id,"rejected","Stale/duplicate signal bar"); return; }
 // Never mix robot exposure with manual/other EA positions or pending orders.
 if(OwnCount()>=PositionLimit() || BlockingPositions()>0 || OrdersTotal()>0) { Ack(id,"rejected","Existing exposure blocks this symbol"); return; }
 MqlTick tick; if(!SymbolInfoTick(_Symbol,tick) || tick.bid<=0 || tick.ask<=tick.bid || TimeTradeServer()-tick.time>120 || TimeTradeServer()<tick.time) { Ack(id,"rejected","Missing/stale quote"); return; }
 double point=SymbolInfoDouble(_Symbol,SYMBOL_POINT), ts=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
 if(ts<=0 || point<=0 || (tick.ask-tick.bid)>dist*.10) { Ack(id,"rejected","Spread too large"); return; }
 double price=(direction>0 ? tick.ask:tick.bid);
 double sl=NormalizeDouble((direction>0 ? MathFloor((price-dist)/ts):MathCeil((price+dist)/ts))*ts,_Digits);
 double tp=NormalizeDouble((direction>0 ? MathCeil((price+reward)/ts):MathFloor((price-reward)/ts))*ts,_Digits);
 double minstop=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*point;
 if((direction>0 ? tick.bid-sl:sl-tick.ask)<minstop || (direction>0 ? tp-tick.bid:tick.ask-tp)<minstop) { Ack(id,"rejected","Broker stop distance"); return; }
 ENUM_ORDER_TYPE type=(direction>0 ? ORDER_TYPE_BUY:ORDER_TYPE_SELL);
 double loss=0,minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
 if(step<=0 || minimum<=0 || !OrderCalcProfit(type,_Symbol,minimum,price,sl,loss) || loss>=0) { Ack(id,"rejected","Cannot calculate risk"); return; }
 // Per-symbol nominal SL risk <=0.05%; each new entry <=0.025%.
 // Fees, execution slippage and gaps are not guaranteed by this estimate.
 double used=OwnRisk(direction),equity=AccountInfoDouble(ACCOUNT_EQUITY);
 if(used<0 || equity<=0) { Ack(id,"rejected","Opposite exposure or missing risk data"); return; }
 double budget=MathMin(equity*.00025,equity*.0005-used);
 if(budget<=0) { Ack(id,"rejected","Symbol risk budget exhausted"); return; }
 double volume=MathFloor((budget/(-loss/minimum))/step)*step;
 volume=NormalizeDouble(MathMin(volume,SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX)),8);
 double actual_loss=0;
 if(volume<minimum || !OrderCalcProfit(type,_Symbol,volume,price,sl,actual_loss) || !MathIsValidNumber(actual_loss) || -actual_loss>budget+.000001) { Ack(id,"rejected","Risk/lot minimum limit"); return; }
 double margin=0;
 if(volume<minimum || !OrderCalcMargin(type,_Symbol,volume,price,margin) || margin+AccountInfoDouble(ACCOUNT_MARGIN)>AccountInfoDouble(ACCOUNT_EQUITY)*.20) { Ack(id,"rejected","Volume/minimum/margin limit"); return; }
 GlobalVariableSet(key+"last_bar",(double)bar); GlobalVariablesFlush();
 trade.SetTypeFillingBySymbol(_Symbol);
 string comment="KH:"+StringSubstr(strat,0,25);
 bool sent=(direction>0 ? trade.Buy(volume,_Symbol,0,sl,tp,comment):trade.Sell(volume,_Symbol,0,sl,tp,comment));
 uint ret=trade.ResultRetcode();
 Ack(id,(sent && (ret==TRADE_RETCODE_DONE || ret==TRADE_RETCODE_DONE_PARTIAL)) ? "executed":"not_confirmed",trade.ResultRetcodeDescription(),trade.ResultOrder(),trade.ResultDeal());
}
void Publish() {
 bool demo=Demo(); MqlTick tick; ZeroMemory(tick); SymbolInfoTick(_Symbol,tick);
 string s="{\"executor_version\":6,\"ea_version\":\"3.23\",\"trade_memory_schema\":1,\"executor_instance\":"+Q(executor_instance)+",\"schema\":2,\"demo\":"+B(demo)+",\"connected\":"+B((bool)TerminalInfoInteger(TERMINAL_CONNECTED))+
 ",\"generated_utc\":"+(string)(long)TimeGMT()+",\"algo_enabled\":"+B(CanTrade())+",\"halted\":"+B(halted)+",\"stopped\":"+B(FileIsExist(BASE+"stop.flag"))+
 ",\"note\":"+Q(last_note)+",\"symbol\":"+Q(_Symbol)+",\"period\":"+(string)(int)_Period+",\"period_seconds\":"+(string)PeriodSeconds(_Period);
 s+=",\"max_positions\":"+(string)PositionLimit()+",\"entry_window_seconds\":"+(string)EntryWindow()+",\"bar_age_seconds\":"+(string)(long)(TimeTradeServer()-iTime(_Symbol,_Period,0));
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
   s+="{\"identifier\":"+(string)PositionGetInteger(POSITION_IDENTIFIER)+",\"ticket\":"+(string)ticket+",\"direction\":"+(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? "1":"-1")+
   ",\"bars_held\":"+(string)iBarShift(_Symbol,_Period,(datetime)PositionGetInteger(POSITION_TIME),false)+
   ",\"profit\":"+DoubleToString(PositionGetDouble(POSITION_PROFIT),2)+",\"comment\":"+Q(PositionGetString(POSITION_COMMENT))+"}";
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
 else if(recovery_action==1) { startup_reconciled=true; ProcessRequest(token); }
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
