#property strict
#property service
#property version "1.00"
#property description "Read-only economic calendar export. No trade operations. Runs separately from chart EAs."

string Quote(string value) {
 StringReplace(value,"\\","\\\\"); StringReplace(value,"\"","\\\"");
 StringReplace(value,"\r"," "); StringReplace(value,"\n"," "); StringReplace(value,"\t"," ");
 return "\""+value+"\"";
}
string Bool(bool value) { return value ? "true":"false"; }
void ExportCalendar() {
 datetime utc=TimeGMT(),server=TimeTradeServer();
 long offset=(long)server-(long)utc;
 string currencies[3]={"USD","EUR","JPY"};
 string events="",complete=""; bool available=TerminalInfoInteger(TERMINAL_CONNECTED) && server>0;
 for(int c=0;c<3;c++) {
  MqlCalendarValue values[];
  ResetLastError();
  int count=CalendarValueHistory(values,server-10800,server+86400,NULL,currencies[c]);
  bool ok=count>=0 && count<=500;
  if(c>0) complete+=",";
  complete+=Quote(currencies[c])+":"+Bool(ok);
  if(!ok) { available=false; continue; }
  for(int i=0;i<count;i++) {
   MqlCalendarEvent e;
   if(!CalendarEventById(values[i].event_id,e)) { available=false; continue; }
   if(e.importance!=CALENDAR_IMPORTANCE_HIGH && e.importance!=CALENDAR_IMPORTANCE_MODERATE) continue;
   if(e.time_mode!=CALENDAR_TIMEMODE_DATETIME) continue;
   if(events!="") events+=",";
   string potential=values[i].impact_type==CALENDAR_IMPACT_POSITIVE ? "positive":values[i].impact_type==CALENDAR_IMPACT_NEGATIVE ? "negative":"unknown";
   events+="{\"id\":"+(string)values[i].id+",\"event_id\":"+(string)e.id+",\"revision\":"+(string)values[i].revision+
    ",\"title\":"+Quote(e.name)+",\"currency\":"+Quote(currencies[c])+",\"importance\":"+Quote(e.importance==CALENDAR_IMPORTANCE_HIGH ? "High":"Moderate")+
    ",\"utc\":"+(string)((long)values[i].time-offset)+",\"actual\":"+(values[i].HasActualValue() ? DoubleToString(values[i].GetActualValue(),8):"null")+
    ",\"forecast\":"+(values[i].HasForecastValue() ? DoubleToString(values[i].GetForecastValue(),8):"null")+
    ",\"previous\":"+(values[i].HasPreviousValue() ? DoubleToString(values[i].GetPreviousValue(),8):"null")+
    ",\"unit\":"+(string)e.unit+",\"multiplier\":"+(string)e.multiplier+",\"potential_impact\":"+Quote(potential)+",\"source_url\":"+Quote(e.source_url)+"}";
  }
 }
 string data="{\"schema\":1,\"source\":\"mt5_economic_calendar_v1\",\"generated_utc\":"+(string)(long)utc+
  ",\"broker_utc_offset_seconds\":"+(string)offset+",\"available\":"+Bool(available)+",\"currencies_complete\":{"+complete+"},\"events\":["+events+"]}";
 string name="khorshid_multi\\shared-news\\mt5_calendar.json";
 int file=FileOpen(name+".tmp",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
 if(file==INVALID_HANDLE) return;
 FileWriteString(file,data); FileFlush(file); FileClose(file);
 FileMove(name+".tmp",0,name,FILE_REWRITE);
}
void OnStart() {
 FolderCreate("khorshid_multi"); FolderCreate("khorshid_multi\\shared-news");
 while(!IsStopped()) { ExportCalendar(); Sleep(60000); }
}
