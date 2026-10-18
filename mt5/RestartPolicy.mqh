// Pure restart decision: 0 = wait, 1 = process current lease, 2 = protective close.
// Kept free of terminal APIs so the same logic can be tested offline.
int RestartPolicy(bool stop_requested,bool active_lease,bool reconciled,long elapsed_ms,bool protected_positions) {
 if(stop_requested) return 2;
 if(active_lease) return 1;
 if(!reconciled && elapsed_ms>=0 && elapsed_ms<15000 && protected_positions) return 0;
 return 2;
}

// Shared MQL/C++ schedule logic. Input intervals use broker-server seconds.
// Merge overlapping sessions before detecting breaks of at least 24 hours.
#ifdef __cplusplus
#define KH_SESSION_ARRAY(name) long* name
#else
#define KH_SESSION_ARRAY(name) long &name[]
#endif
int WeeklyClosePolicy(long now,KH_SESSION_ARRAY(starts),KH_SESSION_ARRAY(ends),int count,long &closes,long &opens) {
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
   return now>=end-600 ? 1:0;
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
