"""Offline reconstruction of executed trades and their contemporaneous decisions.

Reads SQLite journals only. Does not import a broker interface, start services,
fetch news or treat intents/partial exits as completed trades.
"""
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from statistics import mean
from zoneinfo import ZoneInfo
from ultimate_khorshid.tools.trade_memory import position_outcome

SYMBOLS=('XAUUSD','EURUSD','USDJPY')


def read_table(path,query,args=()):
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as con:
        return con.execute(query,args).fetchall()


def local_time(server,offset):
    return datetime.fromtimestamp(server-offset,ZoneInfo('Europe/Stockholm')).isoformat() if offset is not None else None


def aggregate(rows):
    closed=[r for r in rows if r['closed_complete']]
    wins=[r['net'] for r in closed if r['net']>0];losses=[r['net'] for r in closed if r['net']<0]
    return {'closed':len(closed),'wins':len(wins),'losses':len(losses),
        'win_rate':len(wins)/len(closed) if closed else None,
        'net':round(sum(r['net'] for r in closed),2),
        'average_win':round(mean(wins),2) if wins else None,
        'average_loss':round(mean(losses),2) if losses else None,
        'profit_factor':sum(wins)/-sum(losses) if losses else None}


def news_comparison(decision):
    learning=decision.get('learning',{});scores=learning.get('candidates',{});adjustments=learning.get('news_adjustments',{})
    if not scores:return {'status':'no_recorded_candidates'}
    raw={k:float(v)-float(adjustments.get(k,0)) for k,v in scores.items()}
    best=max(raw.values());winners=[k for k,v in raw.items() if abs(v-best)<1e-6]
    if len(winners)!=1:return {'status':'unresolved_without_recorded_tie_break','without_news_candidates':winners}
    selected=decision.get('selected',learning.get('selected'))
    return {'status':'reconstructed_score_ranking','without_news_selected':winners[0],
            'recorded_selected':selected,'selection_changed':selected!=winners[0],
            'has_news_adjustment':any(float(v)!=0 for v in adjustments.values()),
            'profitability_effect':'not_identifiable_from_filled_orders_alone'}


def audit_symbol(root,symbol):
    folder=root/'.khorshid-multi'/symbol;state=json.loads((folder/'state.json').read_text())
    journal=folder/'journal.sqlite';memory=folder/'trade_memory.sqlite'
    raw=[json.loads(r[0]) for r in read_table(journal,'SELECT data FROM deals WHERE run_id=?',(state['id'],))]
    observations={d['ticket']:d for (text,) in read_table(memory,'SELECT data FROM observations WHERE account=? AND symbol=?',(state['login'],symbol)) for d in [json.loads(text)]}
    deals=[{**d,**observations.get(d['ticket'],{})} for d in raw]
    contexts=[json.loads(r[0]) for r in read_table(memory,'SELECT data FROM intents WHERE account=? AND symbol=? AND period=?',(state['login'],symbol,state['period']))]
    contexts=[c for c in contexts if c.get('run_id')==state['id']]
    by_request={c['request_id']:c for c in contexts};by_order={}
    for request,text in read_table(memory,'SELECT request,data FROM acknowledgements WHERE account=?',(state['login'],)):
        ack=json.loads(text);ctx=by_request.get(request)
        if ctx and ctx.get('action')=='open' and ack.get('status') in ('executed','not_confirmed') and ack.get('order'):
            by_order[str(ack['order'])]=ctx
    decisions=[json.loads(r[0]) for r in read_table(memory,'SELECT data FROM decisions WHERE account=? AND symbol=? AND run=?',(state['login'],symbol,state['id']))]
    bars={};conflicts=[]
    for ctx in sorted(contexts,key=lambda c:c['recorded_utc']):
        for bar in ctx.get('recent_closed_bars',[]):
            if bar['time'] in bars and bars[bar['time']]!=bar:conflicts.append(bar['time'])
            bars[bar['time']]=bar
    grouped={}
    for d in deals:grouped.setdefault(str(d['position_id']),[]).append(d)
    open_ids={ident for ident,ds in grouped.items() if abs(sum(d['volume'] for d in ds if d['entry']==0)-sum(d['volume'] for d in ds if d['entry'] in (1,3)))>1e-8}
    trades=[]
    for ident,ds in grouped.items():
        ds.sort(key=lambda d:(d['time'],d['ticket']))
        out=position_outcome(state['login'],symbol,ds,open_ids,by_order,state['currency'])
        entries=[d for d in ds if d['entry']==0];exits=[d for d in ds if d['entry'] in (1,3)]
        if len(out['entry_contexts'])!=len(entries):
            out.update(learning_eligible=False,normalized_reward=None)
            out['evidence_problems'].append('entry_decision_link_unavailable')
        ctx=out['entry_contexts'][0] if len(out['entry_contexts'])==1 else {}
        decision=ctx.get('decision',{});learning=decision.get('learning',{});strategy=out['strategy']
        details=learning.get('score_details',{}).get(strategy,{})
        risks=[d.get('initial_risk') or {} for d in entries]
        offsets=[round((d['time']-r['captured_utc'])/900)*900 for d,r in zip(entries,risks) if isinstance(r.get('captured_utc'),(int,float)) and abs(d['time']-r['captured_utc'])<=14*3600]
        offset=offsets[0] if offsets and len(set(offsets))==1 else None
        opened=min((d['time'] for d in entries),default=None);closed=max((d['time'] for d in exits),default=None)
        period=state['period']*60 if state['period'] in (1,5,15,30,60) else None
        side=ctx.get('direction');price=entries[0]['price'] if len(entries)==1 else None
        sl=risks[0].get('sl') if len(risks)==1 else None
        future=None
        if out['closed_complete'] and 4 in out['exit_reasons'] and period and price and side in (-1,1):
            first=(closed//period+1)*period
            available=[bars.get(first+i*period) for i in range(3)]
            if all(available):
                future={'horizon_bars':3,'coverage':'complete_three_subsequent_closed_candles',
                    'revisited_entry_bid':any(b['high']>=price if side>0 else b['low']<=price for b in available),
                    'interpretation':'Descriptive bid OHLC only; not an executable alternative trade or profit estimate'}
            else:future={'coverage':'incomplete','horizon_bars':3}
        row={k:v for k,v in out.items() if k!='entry_contexts'}
        row.update(run_id=state['id'],period=state['period'],opened_server=opened,closed_server=closed,
            opened_local=local_time(opened,offset) if opened else None,closed_local=local_time(closed,offset) if closed else None,
            broker_utc_offset_seconds=offset,holding_minutes=(closed-opened)/60 if opened and closed else None,
            direction=side,entry_price=price,initial_sl=sl,initial_distance=abs(price-sl) if price and sl else None,
            exit_prices=[d['price'] for d in exits],entry_request=ctx.get('request_id'),
            context_linked=bool(ctx),entry_context=decision.get('market_context'),
            prior_verified_results=details.get('demo_results'),exploration_bonus=details.get('exploration_bonus'),
            exploration_used=isinstance(details.get('exploration_bonus'),(int,float)) and details['exploration_bonus']>0,
            news_score_comparison=news_comparison(decision),exit_profile=decision.get('plan',{}).get('exit_profile'),
            entry_plan=decision.get('plan'),post_stop_observation=future,
            position_scaling=decision.get('portfolio',{}).get('position_scaling'),
            recorded_exit_requests=[{'utc':c['recorded_utc'],'plan':c.get('decision',{}).get('plan',{})} for c in contexts if c.get('action')=='close_tickets' and any(str(t)==ident for t in c.get('tickets',[]))])
        trades.append(row)
    evaluations=[]
    for path in sorted((folder/'evaluations'/state['id']).glob('*.json')):
        r=json.loads(path.read_text());evaluations.append({'file':str(path.relative_to(root)),'selected':r.get('selected'),'candidate_before_holdout':r.get('candidate_before_holdout'),'last_bar':r.get('last_bar')})
    summary={'symbol':symbol,'run_id':state['id'],'started_utc':state['started_utc'],'last_snapshot_utc':state['last_snapshot_utc'],
        **aggregate(trades),'last_known_unclosed':sum(not t['closed_complete'] for t in trades),
        'strategies':{name:aggregate([r for r in trades if r['strategy']==name]) for name in sorted({t['strategy'] for t in trades})},
        'exploratory_closed':sum(t['closed_complete'] and t['exploration_used'] for t in trades),
        'closed_without_prior_verified_results':sum(t['closed_complete'] and t['prior_verified_results']==0 for t in trades),
        'exit_reasons':{str(reason):sum(t['closed_complete'] and reason in t['exit_reasons'] for t in trades) for reason in (0,3,4,5)},
        'screenings':evaluations,'news_decisions_with_adjustment':sum(any(v!=0 for v in d.get('learning',{}).get('news_adjustments',{}).values()) for d in decisions),
        'recorded_candle_count':len(bars),'conflicting_candles':sorted(set(conflicts)),
        'start_balance':state.get('start_balance'),'last_balance':state.get('balance'),'last_equity':state.get('equity')}
    return summary,trades,sorted(bars.values(),key=lambda b:b['time'])


def build(root,output):
    output.mkdir(parents=True,exist_ok=True);summaries=[];trades=[];sources={}
    for symbol in SYMBOLS:
        folder=root/'.khorshid-multi'/symbol
        for name in ('journal.sqlite','trade_memory.sqlite','state.json'):
            p=folder/name;sources[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
        summary,rows,bars=audit_symbol(root,symbol);summaries.append(summary);trades.extend(rows)
        (output/(symbol+'-reconstructed-bars.json')).write_text(json.dumps(bars,indent=2))
    total=aggregate(trades)
    closed=[t for t in trades if t['closed_complete']]
    subsequent=[t for t in closed if (t.get('post_stop_observation') or {}).get('coverage')=='complete_three_subsequent_closed_candles']
    news=[t['news_score_comparison'] for t in closed]
    findings={'exploration_in_closed_entry_scores':sum(t['exploration_used'] for t in closed),
        'closed_without_prior_verified_results':sum(t['prior_verified_results']==0 for t in closed),
        'saved_screenings':sum(len(s['screenings']) for s in summaries),
        'saved_screenings_with_selected_candidate':sum(bool(e['selected']) for s in summaries for e in s['screenings']),
        'news_adjusted_filled_entries':sum(n.get('has_news_adjustment',False) for n in news),
        'news_ranking_changes_among_resolved_entries':sum(n.get('selection_changed',False) for n in news),
        'unresolved_news_ranking_ties':sum(n['status']=='unresolved_without_recorded_tie_break' for n in news),
        'news_profitability_ab':'Not measured; a ranking reconstruction is not an independent A/B replay.',
        'staged_exits':sum(t['exit_profile']=='staged' for t in closed),
        'countertrend_entries':{symbol:aggregate([t for t in closed if t['symbol']==symbol and
            ((t.get('entry_context') or {}).get('trend'),t.get('direction')) in (('down',1),('up',-1))]) for symbol in SYMBOLS},
        'additional_position_entries':aggregate([t for t in closed if (t.get('position_scaling') or {}).get('existing_positions',0)>0]),
        'post_stop_complete_three_bar_windows':len(subsequent),
        'post_stop_revisited_entry_bid':sum(t['post_stop_observation']['revisited_entry_bid'] for t in subsequent),
        'by_market_context':{symbol:{trend:aggregate([t for t in closed if t['symbol']==symbol and (t.get('entry_context') or {}).get('trend')==trend])
            for trend in ('up','down','range')} for symbol in SYMBOLS}}
    result={'schema':1,'scope':'Latest recorded run per symbol; complete positions only',
        'live_status':'unavailable; MetaTrader remains closed by user request',
        'summary':total,'findings':findings,'symbols':summaries,'trades':trades,'input_sha256':sources,
        'limitations':['One overnight demo period is not independent validation.',
            'Open/partial positions are excluded from closed-trade results; their current status is unknown.',
            'Post-stop candle observations and no-news score rankings do not establish counterfactual profits.',
            'Zero reported commissions do not remove spread/slippage in entry and exit prices.',
            'Reconstructed candles are partial; missing bars are not fabricated.']}
    (output/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    fields=('symbol','position_id','strategy','closed_complete','net','risk_cash','normalized_reward','opened_local','closed_local','holding_minutes','direction','entry_price','initial_sl','initial_distance','exit_profile','prior_verified_results','exploration_bonus','context_linked')
    with (output/'trades.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows({k:r.get(k) for k in fields} for r in trades)
    lines=['# ممیزی معاملات ثبت‌شده — ۲۲ اکتبر ۲۰۲۶','',
        f"نتیجهٔ {total['closed']} پوزیشن کاملاً بسته‌شده: {total['net']:+.2f} دلار؛ {total['wins']} سودده و {total['losses']} زیان‌ده.",
        '', 'متاتریدر باز نشده و وضعیت زندهٔ پوزیشن باقی‌مانده تأیید نشده است.','',
        '| نماد | بسته‌شده | خالص دلار | ورود اکتشافی | بدون نتیجهٔ معتبر قبلی برای استراتژی |','|---|---:|---:|---:|---:|']
    for s in summaries:lines.append(f"| {s['symbol']} | {s['closed']} | {s['net']:+.2f} | {s['exploratory_closed']} | {s['closed_without_prior_verified_results']} |")
    lines+=['','در مسیر قبلی، امتیاز اکتشاف در انتخاب سفارش دخیل بود. مجوز معامله از قبولی غربال‌گری تاریخی جدا بود؛ قبولی تست نرم‌افزار هم شاهد سودآوری نیست.','',
        f"از {findings['saved_screenings']} گزارش غربال‌گری ذخیره‌شده برای این دوره، {findings['saved_screenings_with_selected_candidate']} گزارش گزینهٔ منتخب داشته است. این شاهد معماری است؛ برای هر سفارش، تقدم زمانی غربال‌گری خاصی بر ورود ادعا نمی‌شود.",'',
        f"در {findings['news_adjusted_filled_entries']} ورود، امتیاز خبر غیرصفر بوده است. بازسازی رتبه‌بندیِ قابل‌حل، {findings['news_ranking_changes_among_resolved_entries']} تغییر در انتخاب نشان می‌دهد؛ {findings['unresolved_news_ranking_ties']} حالت به‌دلیل نبود جزئیات tie-break قطعی نیست. هیچ‌کدام آزمون سودآوری نسخهٔ بدون خبر نیستند.",'',
        f"در {findings['post_stop_complete_three_bar_windows']} خروج SL که سه کندل بعدی کامل در آرشیو تصمیم‌ها موجود است، قیمت bid در {findings['post_stop_revisited_entry_bid']} مورد دوباره به قیمت ورود رسیده است. حجم نمونه کوچک است؛ ترتیب tick، اسپرد، هزینه و بازده معاملهٔ فرضی معلوم نیست. این عدد به‌تنهایی توجیه بازترکردن حد ضرر نیست.",'',
        f"ورودهای خلاف روندِ ثبت‌شده در USDJPY: {findings['countertrend_entries']['USDJPY']['closed']} معامله و {findings['countertrend_entries']['USDJPY']['net']:+.2f} دلار خالص. استراتژی بازگشتی می‌تواند عمداً خلاف روند وارد شود؛ این مشاهده به معنی جابه‌جایی اشتباه buy/sell یا اثبات علت زیان نیست.",'',
        f"پوزیشن‌های اضافهٔ دارای زمینهٔ ثبت‌شده: {findings['additional_position_entries']['closed']} معامله، خالص {findings['additional_position_entries']['net']:+.2f} دلار. سودده‌بودن پوزیشن قبلی، سود پوزیشن اضافه را تضمین نکرده است.",'',
        '## محدودیت‌های نتیجه','',
        'هر پوزیشن به سفارش تأییدشده و زمینهٔ همان ورود پیوند داده شده است. CSV شامل پوزیشن باز نیز هست و ستون closed_complete آن را متمایز می‌کند. JSON جزئیات دلایل خروج، ارزیابی خبر و زمینهٔ ورود را نگه می‌دارد.','',
        'تنها از روی سفارش‌های انجام‌شده نمی‌توان سود نسخهٔ بدون خبر یا حد ضرر متفاوت را محاسبه کرد. دادهٔ مفقود و تصمیم‌های فرضی جای نتیجهٔ واقعی گذاشته نشده‌اند.']
    (output/'REPORT_FA.md').write_text('\n'.join(lines)+'\n')
    for relative,digest in sources.items():
        if hashlib.sha256((root/relative).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Audit input changed while reading: '+relative)
    return result
