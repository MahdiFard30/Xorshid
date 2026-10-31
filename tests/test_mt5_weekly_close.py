"""Execute the same calendar policy used by the EA, without broker access."""
from pathlib import Path
import shutil
import subprocess

import pytest

from ultimate_khorshid.tools.mt5_entry_policy import weekly_gate

DAY = 86400
# Times relative to Monday midnight (positive epoch for policy clock validation).
MONDAY = 1704067200
FRIDAY_END = MONDAY + 5 * DAY
SUNDAY_OPEN = MONDAY + 6 * DAY + 23 * 3600


@pytest.fixture(scope="module")
def calendar_binary(tmp_path_factory):
    compiler = shutil.which("g++")
    if not compiler:
        pytest.skip("C++ compiler required for shared MQL policy")
    folder = tmp_path_factory.mktemp("weekly-calendar")
    header = Path(__file__).resolve().parents[1] / "mt5/RestartPolicy.mqh"
    source = folder / "calendar.cpp"
    source.write_text('#include <iostream>\n#include <cstdlib>\n#include "' + str(header) + '"\n'
                      'int main(int n,char** v){if(std::string(v[1])=="pending"){std::cout<<WeeklyExitPending(atoi(v[2]),atoi(v[3]),atoi(v[4]),atoi(v[5]));return 0;} '
                      'if(std::string(v[1])=="offsets"){long a=0,b=0;bool valid=TradingSessionOffsets(atol(v[2]),atol(v[3]),a,b);std::cout<<valid<<" "<<a<<" "<<b;return 0;} '
                      'long s[1024],e[1024],close=0,open=0; '
                      'int count=(n-2)/2; for(int i=0;i<count;i++){s[i]=atol(v[2+i*2]);e[i]=atol(v[3+i*2]);}'
                      'std::cout<<WeeklyClosePolicy(atol(v[1]),s,e,count,close,open)<<" "<<close<<" "<<open;}')
    binary = folder / "calendar"
    subprocess.run([compiler, str(source), "-o", str(binary)], check=True, capture_output=True)
    return binary


def evaluate(binary, now, intervals):
    args = [str(binary), str(now), *(str(value) for pair in intervals for value in pair)]
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return tuple(map(int, result.stdout.split()))


def sessions():
    return [(MONDAY + day*DAY, MONDAY + (day+1)*DAY) for day in range(5)] + [
        (SUNDAY_OPEN, MONDAY + 8*DAY)]


@pytest.mark.parametrize("offset,expected", [(-601,0),(-600,1),(-599,1),(0,1),(3600,1),(DAY,1)])
def test_exact_ten_minute_boundary_and_weekend(calendar_binary, offset, expected):
    assert evaluate(calendar_binary, FRIDAY_END+offset, sessions()) == (expected, FRIDAY_END, SUNDAY_OPEN)


def test_reopens_at_actual_broker_session_start(calendar_binary):
    assert evaluate(calendar_binary, SUNDAY_OPEN, sessions())[0] == 0
    assert evaluate(calendar_binary, SUNDAY_OPEN-1, sessions())[0] == 1


def test_short_daily_break_does_not_trigger_weekly_liquidation(calendar_binary):
    intervals = [(MONDAY+d*DAY+3600, MONDAY+(d+1)*DAY-3600) for d in range(5)]
    intervals.append((SUNDAY_OPEN, MONDAY+8*DAY))
    assert evaluate(calendar_binary, MONDAY+DAY-600, intervals)[0] == 0


def test_overnight_friday_session_ends_saturday(calendar_binary):
    end = FRIDAY_END+2*3600
    intervals = [(MONDAY, end), (SUNDAY_OPEN, MONDAY+8*DAY)]
    assert evaluate(calendar_binary, end-601, intervals)[0] == 0
    assert evaluate(calendar_binary, end-600, intervals) == (1,end,SUNDAY_OPEN)


def test_unsorted_overlapping_sessions_are_merged(calendar_binary):
    intervals = [(SUNDAY_OPEN, MONDAY+8*DAY), (MONDAY+DAY,FRIDAY_END), (MONDAY,MONDAY+2*DAY)]
    assert evaluate(calendar_binary, FRIDAY_END-600, intervals) == (1,FRIDAY_END,SUNDAY_OPEN)


@pytest.mark.parametrize("now,intervals", [(MONDAY,[]),(MONDAY,[(MONDAY,FRIDAY_END)]),
    (0,[(MONDAY,FRIDAY_END),(SUNDAY_OPEN,MONDAY+8*DAY)]),
    (MONDAY-1,[(MONDAY,FRIDAY_END),(SUNDAY_OPEN,MONDAY+8*DAY)]),
    (MONDAY,[(MONDAY,MONDAY),(SUNDAY_OPEN,MONDAY+8*DAY)])])
def test_missing_or_invalid_schedule_is_unknown(calendar_binary,now,intervals):
    assert evaluate(calendar_binary,now,intervals)[0] == -1


def test_continuous_market_has_no_weekend_blackout(calendar_binary):
    intervals = [(MONDAY+d*DAY, MONDAY+(d+1)*DAY) for d in range(9)]
    assert evaluate(calendar_binary, FRIDAY_END-600, intervals) == (0,0,0)


@pytest.mark.parametrize("snapshot", [{"weekly_close_paused":True,"weekly_schedule_known":True},
    {"weekly_schedule_known":False}, {"weekly_schedule_known":"invalid"}])
def test_worker_blocks_entry_on_blackout_or_unknown_schedule(snapshot):
    assert "action" not in weekly_gate({"action":"open","reason":"signal"},snapshot)


def test_worker_preserves_exit_and_legacy_compatibility():
    close = {"action":"close_tickets","tickets":[12]}
    assert weekly_gate(close,{"weekly_close_paused":True}) == close
    entry = {"action":"open"}
    assert weekly_gate(entry,{}) == entry
    assert weekly_gate(entry,{"weekly_close_paused":False,"weekly_schedule_known":True}) == entry


@pytest.mark.parametrize('pending,state,connected,positions,expected',[
    (False,1,True,2,True),  # Closing window starts liquidation.
    (True,0,True,1,True),  # Reopening cannot cancel unfinished exits.
    (True,-1,False,0,True),  # Missing connection cannot confirm completion.
    (True,0,True,0,False),  # Clear only after terminal confirms no position.
    (False,1,True,0,False),
    (False,0,True,1,False),  # No arbitrary liquidation outside a weekly close.
])
def test_unfinished_exit_survives_reopening_and_disconnect(calendar_binary,pending,state,connected,positions,expected):
    result=subprocess.run([str(calendar_binary),'pending',*map(str,map(int,(pending,state,connected,positions)))],
                          check=True,capture_output=True,text=True)
    assert bool(int(result.stdout)) is expected


@pytest.mark.parametrize('begin,finish,expected',[
    (0,0,(0,0,0)),(3600,3600,(0,0,0)),
    (0,86400,(1,0,86400)),(0,82800,(1,0,82800)),
    (82800,7200,(1,82800,93600)),(-1,0,(0,0,0)),
])
def test_empty_rows_are_not_full_days_but_real_full_days_remain(calendar_binary,begin,finish,expected):
    raw=subprocess.check_output([str(calendar_binary),'offsets',str(begin),str(finish)],text=True)
    assert tuple(map(int,raw.split()))==expected


def test_actual_gold_saturday_empty_row_pauses_from_friday_and_reopens_monday(calendar_binary):
    intervals=[]
    # Actual broker rows: Mon-Fri 0->82800, Sat 0->0, Sun absent.
    for day in range(9):
        weekday=day%7
        if weekday==6:continue
        begin,finish=(0,0) if weekday==5 else (0,82800)
        raw=subprocess.check_output([str(calendar_binary),'offsets',str(begin),str(finish)],text=True)
        valid,a,b=map(int,raw.split())
        if valid:intervals.append((MONDAY+day*DAY+a,MONDAY+day*DAY+b))
    friday_close=MONDAY+4*DAY+82800;reopen=MONDAY+7*DAY
    assert evaluate(calendar_binary,friday_close-601,intervals)[0]==0
    assert evaluate(calendar_binary,friday_close-600,intervals)==(1,friday_close,reopen)
    assert evaluate(calendar_binary,MONDAY+5*DAY+12*3600,intervals)==(1,friday_close,reopen)
    assert evaluate(calendar_binary,reopen-1,intervals)[0]==1
    assert evaluate(calendar_binary,reopen,intervals)[0]==0
