"""Run independent report-only post-trade review; no broker writes or scoring."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ultimate_khorshid.tools.post_trade_review import ReviewStore,collect

LABELS={
    'negative_entry_evidence':'ورود با شواهد منفی',
    'adverse_similar_market_history':'سابقهٔ نامساعد شرایط مشابه',
    'entry_against_recorded_trend':'ورود خلاف روند ثبت‌شده؛ ممکن است عمدی باشد',
    'full_allocation_with_limited_demo_history':'حجم کامل با سابقهٔ محدود دمو',
    'explicit_cost_drag':'هزینهٔ صریح قابل‌توجه نسبت به ریسک',
    'adverse_fill_vs_recorded_request':'اجرای نامساعد نسبت به قیمت درخواست؛ علت اختلاف قطعی نیست',
}


def atomic(path,text):
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w') as f:f.write(text);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def run_once(root,terminal,output):
    store=ReviewStore(output/'reviews.sqlite')
    result=collect(root,terminal,store)
    reviews=result.pop('reviews')
    store.record_run(result)
    atomic(output/'summary.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    # Complete revisions remain in SQLite; this is only a convenient view.
    closed=sorted((r for r in reviews if r['assessment_status']=='provisional'),
                  key=lambda r:r['facts'].get('closed_time_server') or 0,reverse=True)
    atomic(output/'latest-reviews.json',json.dumps(closed[:20],ensure_ascii=False,indent=2)+'\n')
    lines=['# ارزیابی پس از معامله — فقط گزارش','',
           'علت قطعی شکست تعیین نشده است؛ موارد زیر شواهد و عوامل احتمالی‌اند، نه اثبات علت.',
           'این ارزیابی روی انتخاب استراتژی، حجم، ورود یا خروج اثر ندارد.','',
           f"تعداد پوزیشن بررسی‌شده: {result['reviewed_positions']}؛ سودده: {result['results'].get('win',0)}؛ زیان‌ده: {result['results'].get('loss',0)}؛ باز یا ناقص: {result['results'].get('open_or_incomplete',0)}",
           f"خطاهای خواندن: {result['errors'] or 'ندارد'}",
           'سوابق پیش از اصلاح روبات هم در این گزارش وجود دارند؛ زمان ورود و نسخه در جزئیات JSON ثبت شده‌اند.','',
           '## آخرین معاملات بسته‌شده','']
    for r in closed[:20]:
        s=r['scope'];factors='؛ '.join(LABELS[f['label']] for f in r['possible_factors']) or 'عامل مشخصی با شواهد موجود پیدا نشد'
        lines.extend([f"- {s['symbol']} / {s['strategy']} / پوزیشن {s['position_id']}: خالص {r['facts']['net']:+.2f}؛ {factors}."])
    lines.extend(['','ثبت سود یا ضرر به‌تنهایی درست یا غلط بودن تصمیم را ثابت نمی‌کند.',
                  'مسیر کامل تیک‌ها و نتیجهٔ خروج جایگزین موجود نیست؛ تشخیص شکست کاذب و ورود دیرهنگام هنوز تأیید نمی‌شود.',
                  'الگوهای تکرارشونده در summary.json صرفاً توصیفی‌اند و هنوز ارزش پیش‌بینی آن‌ها سنجیده نشده است.'])
    atomic(output/'REPORT_FA.md','\n'.join(lines)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--terminal',type=Path,default=Path.home()/'.mt5/drive_c/Program Files/MetaTrader 5')
    args=parser.parse_args();output=ROOT/'.khorshid-research/post-trade';output.mkdir(parents=True,exist_ok=True)
    with (output/'watcher.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 0
        while True:
            try:
                result=run_once(ROOT,args.terminal,output)
                print(json.dumps({k:result[k] for k in ('updated_utc','new_revisions','reviewed_positions','errors')},ensure_ascii=False),flush=True)
            except Exception as exc:
                failure={'utc':time.time(),'error':type(exc).__name__+': '+str(exc)}
                print(json.dumps(failure,ensure_ascii=False),flush=True)
                with (output/'failures.jsonl').open('a') as f:
                    f.write(json.dumps(failure,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
                if not args.watch:return 1
            if not args.watch:return 0
            time.sleep(30)


if __name__=='__main__':raise SystemExit(main())
