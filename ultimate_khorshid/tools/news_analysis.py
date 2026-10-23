"""Explain scheduled and released economic news without guessing missing values.

Uses cached calendar data only. Direction is a provider hypothesis checked
against observed closed candles; it never creates an entry or raises risk.
"""
import math
from ultimate_khorshid.tools.mt5_news_calendar import assess, CURRENCIES
from ultimate_khorshid.tools.market_learning import describe

SOURCE='mt5_economic_calendar_v1'


def number(value):
    return type(value) in (int,float) and math.isfinite(value)


def reaction(snapshot,event_utc,now):
    offset=snapshot.get('broker_utc_offset_seconds')
    if not number(offset) or abs(offset)>14*3600:
        return {'status':'broker_clock_unknown'}
    period=snapshot['period_seconds']
    bars=[b for b in snapshot['bars'] if b['time']-offset+period<=now]
    before=[b for b in bars if b['time']-offset+period<=event_utc]
    after=[b for b in bars if b['time']-offset>=event_utc]
    if not before or not after:
        return {'status':'waiting_for_complete_post_release_candle'}
    context=describe(before)
    if not context or context['atr']<=0:
        return {'status':'insufficient_pre_release_history'}
    change=after[-1]['close']-before[-1]['close']
    return {'status':'observed','change_pct':100*change/before[-1]['close'],
            'change_atr':change/context['atr'],
            'direction':1 if change>context['atr']*.1 else -1 if change<-context['atr']*.1 else 0,
            'last_closed_bar_utc':after[-1]['time']-offset+period}


def analyze(symbol,snapshot,calendar,releases,now):
    schedule=assess(calendar.get('events',[]),calendar.get('fetched_utc',0),symbol,now,calendar.get('error',''),snapshot.get('trading_controls'))
    valid=(releases.get('source')==SOURCE and releases.get('schema')==1
           and number(releases.get('generated_utc')) and -5<=now-releases['generated_utc']<=300
           and releases.get('available') is True)
    complete=releases.get('currencies_complete',{})
    valid=valid and all(complete.get(currency) is True for currency in CURRENCIES[symbol])
    events=releases.get('events',[]) if valid else []
    if not isinstance(events,list) or len(events)>500:
        valid=False;events=[]
    evidence=[]; directions=[];native_blocked=[]
    seen=set()
    for event in events:
        currency=event.get('currency'); utc=event.get('utc')
        if currency not in CURRENCIES[symbol] or not number(utc) or event.get('importance') not in ('High','Moderate'):
            continue
        token=(event.get('id'),event.get('revision',0))
        if token in seen:
            continue
        seen.add(token)
        if event['importance']=='High' and utc-1800<=now<=utc+900:
            native_blocked.append({'title':event.get('title',''),'currency':currency,'utc':utc})
        if not 0<=now-utc<=3*3600:
            continue
        actual,forecast=event.get('actual'),event.get('forecast')
        available=number(actual) and number(forecast)
        item={'id':event.get('id'),'revision':event.get('revision',0),'title':str(event.get('title',''))[:250],
              'currency':currency,'utc':utc,'observed_utc':releases['generated_utc'],
              'actual':actual if number(actual) else None,'forecast':forecast if number(forecast) else None,
              'previous':event.get('previous') if number(event.get('previous')) else None,
              'unit':event.get('unit'),'multiplier':event.get('multiplier'),
              'difference':actual-forecast if available else None,
              'status':'released_comparison' if available else 'actual_or_forecast_missing',
              'source_url':str(event.get('source_url',''))[:500]}
        impact=event.get('potential_impact')
        sign=1 if impact=='positive' else -1 if impact=='negative' else 0
        # FX quote/base orientation; USD/gold inversion is only a test hypothesis.
        orientation=1 if (symbol=='USDJPY' and currency=='USD') or (symbol=='EURUSD' and currency=='EUR') else -1
        # A revised value cannot explain the market reaction to its original release.
        proposed=sign*orientation if available and actual!=forecast and event.get('revision',0)==0 else 0
        observed=reaction(snapshot,utc,now)
        item.update(potential_symbol_direction=proposed,market_reaction=observed)
        if proposed and observed.get('direction')==proposed:
            item['interpretation']='provider_hypothesis_matches_observed_price'
            directions.append(proposed)
        elif proposed and observed.get('direction')==-proposed:
            item['interpretation']='price_disagrees_with_provider_hypothesis'
        else:
            item['interpretation']='no_confirmed_direction'
        evidence.append(item)
    if native_blocked:
        schedule={**schedule,'allow_entry':False,'status':'news_window',
                  'reason':'Native high-impact event entry window','native_blocking_events':native_blocked}
    bias=directions[0] if directions and len(set(directions))==1 else 0
    return {'version':1,'symbol':symbol,'updated_utc':now,'schedule':schedule,
            'release_data_status':'fresh' if valid else 'unavailable_or_incomplete',
            'confirmed_direction':bias,'evidence':sorted(evidence,key=lambda e:e['utc'])[-10:],
            'conflicting_events':len(set(directions))>1,
            'note':'Actual minus forecast is descriptive, not a trade signal. No missing actual values or headline sentiment are invented.'}


def risk_factor(analysis,direction):
    if not analysis['schedule']['allow_entry']:
        return 0.
    if analysis.get('conflicting_events'):
        return .5
    bias=analysis.get('confirmed_direction',0)
    return .5 if bias and bias==-direction else 1.
