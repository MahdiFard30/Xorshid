"""Chat/CLI compatibility bridge to the installed three-symbol DEMO controller.

No trading starts on import. Every operation runs mt5_multi in an isolated
process, using the same Python interpreter and project as the chat application.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ('XAUUSD', 'EURUSD', 'USDJPY')
NAMES = {'XAUUSD': 'طلا', 'EURUSD': 'یورو به دلار', 'USDJPY': 'دلار به ین'}
STATES = {
    'waiting_for_trend_confirmation': 'منتظر تأیید روند برای سیگنال تازه',
    'research_only': 'ارسال سفارش غیرفعال؛ فقط پژوهش',
    'screening': 'در حال بررسی استراتژی‌ها',
    'waiting_for_entry_signal': 'منتظر سیگنال ورود',
    'waiting_for_next_bar': 'منتظر کندل جدید',
    'managing_demo_position': 'در حال مدیریت معاملهٔ باز',
    'market_closed_or_stale_quote': 'منتظر قیمت تازه',
    'spread_too_large': 'فاصلهٔ خرید و فروش بیشتر از حد مجاز',
    'order_requested': 'درخواست سفارش ارسال شده؛ اجرا هنوز تأیید نشده',
    'order_executed': 'اجرای سفارش تأیید شده',
    'order_rejected': 'درخواست سفارش رد شده',
    'order_not_confirmed': 'اجرای سفارش تأیید نشده',
    'algo_disabled': 'معاملهٔ الگوریتمی غیرفعال است',
    'other_account_exposure': 'معاملات یا سفارش‌های دیگر مانع ورودند',
    'data_unavailable': 'داده در دسترس نیست',
    'stopping': 'در حال توقف',
    'stop_pending': 'درخواست توقف ثبت شده؛ بسته‌شدن معاملات تأیید نشده',
    'stopped': 'متوقف',
    'never_started': 'هنوز شروع نشده',
}


def summarize(out, action):
    if out.get('error'):
        return 'خطا در کنترل ربات سه‌نمادی: ' + str(out['error'])
    rows = out.get('symbols')
    if not isinstance(rows, dict):
        raise ValueError('پاسخ کنترل‌کننده فاقد وضعیت نمادهاست.')
    parts = []
    for symbol in SYMBOLS:
        row = rows.get(symbol)
        if not isinstance(row, dict):
            parts.append(NAMES[symbol] + ': وضعیت دریافت نشد.'); continue
        if row.get('status') == 'starting' and action == 'start':
            parts.append(NAMES[symbol] + ': شروع پردازش تأیید شد؛ هنوز اجرای معامله تأیید نشده.'); continue
        if row.get('error') or not row.get('fresh_snapshot'):
            parts.append(NAMES[symbol] + ': وضعیت زنده قابل تأیید نیست. ' + str(row.get('error') or 'گزارش تازه در دسترس نیست.'))
            continue
        alive = row.get('runner_alive')
        process = 'پردازش روشن است' if alive is True else ('پردازش خاموش است' if alive is False else 'وضعیت پردازش نامشخص است')
        count = row.get('robot_open_positions')
        position = (f'{count} معاملهٔ باز دارد' if isinstance(count, int) and count >= 0 else 'تعداد معاملات باز نامشخص است')
        state = STATES.get(row.get('status'), 'وضعیت: ' + str(row.get('status', 'نامشخص')))
        text = f'{NAMES[symbol]}: {process}؛ {position}؛ {state}.'
        if row.get('selected'): text += ' استراتژی: ' + str(row['selected']) + '.'
        # A historical acknowledgement is not evidence of a newly opened trade.
        if row.get('status') in ('order_rejected', 'order_not_confirmed') and row.get('last_reason'):
            text += ' علت: ' + str(row['last_reason']) + '.'
        parts.append(text)
    if action == 'start': parts.append('شروع برنامه به معنی ورود فوری نیست؛ معامله به سیگنال و شرایط اجرا وابسته است.')
    if action == 'stop':
        parts.append('توقف پردازش‌ها و نبود معاملهٔ باز تأیید شد.' if out.get('stop_confirmed') is True else 'بسته‌شدن همهٔ معاملات هنوز تأیید نشده؛ متاتریدر و اجازهٔ معامله روشن بمانند.')
    return '\n'.join(parts)


def portfolio_action(action):
    if action not in ('start', 'stop', 'status', 'report'):
        raise ValueError('Unknown portfolio action')
    target = ROOT/'ultimate_khorshid/tools/mt5_multi.py'
    if not target.is_file():
        raise ValueError('کنترل‌کنندهٔ mt5_multi نصب نیست؛ نسخهٔ سه‌نمادی را نصب کن.')
    try:
        result = subprocess.run([sys.executable, '-m', 'ultimate_khorshid.tools.mt5_multi', action],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=45)
    except subprocess.TimeoutExpired:
        # Do not retry a mutation: the child may already have applied it.
        raise ValueError('پاسخ کنترل‌کننده دیر رسید؛ نتیجه نامشخص است. دستور را تکرار نکن؛ وضعیت را بررسی کن.') from None
    try: out = json.loads(result.stdout)
    except (TypeError, ValueError):
        raise ValueError('خروجی کنترل‌کننده معتبر نیست. ' + result.stderr[-1500:]) from None
    if not isinstance(out, dict): raise ValueError('Invalid portfolio response')
    if result.returncode and not out.get('error'):
        out['error'] = 'کنترل‌کننده با خطا پایان یافت. ' + result.stderr[-1500:]
    out['scope'] = 'three_symbol_demo'
    out['summary'] = summarize(out, action)
    return out


def start(): return portfolio_action('start')
def stop(wait=8): return portfolio_action('stop')
def report(refresh=True): return portfolio_action('report')


def direct_command(text):
    t = re.sub(r'[^\w\s]', ' ', text.lower().replace('ي','ی').replace('ك','ک').replace('\u200c',' '))
    t = re.sub(r'\s+', ' ', t).strip()
    for _ in range(4):
        for filler in ('سلام ', 'خورشید ', 'لطفا ', 'لطفاً '):
            if t.startswith(filler): t = t[len(filler):].strip(); break
        else: break
    if t in ('توقف کن','توقف کن توقف کن','ترید رو متوقف کن','معامله رو متوقف کن','توقف معاملات','stop trading','stop'): return 'stop'
    if t in ('تمرین دمو رو شروع کن','معامله دمو رو شروع کن','شروع تمرین دمو','start demo trading'): return 'start'
    if t in ('گزارش معاملات','نتیجه معاملات','گزارش تمرین','وضعیت تمرین دمو'): return 'report'
    if t in ('الان داری ترید انجام میدی','الان داری ترید انجام می دی','داری ترید میکنی','داری ترید می کنی',
             'الان داری ترید میکنی','الان داری ترید می کنی','وضعیت معاملات','وضعیت ربات','status'): return 'status'
    return None


def direct_result(query):
    action = direct_command(query)
    if action is None: return None
    from ultimate_khorshid.agents.base import AgentResult
    r = MT5DemoTool().execute(action=action)
    metadata = getattr(r, 'metadata', None) or {}
    return AgentResult(content=metadata.get('summary',r.content), tool_results=[r],
                       metadata={'agent':'demo-controller','model':'deterministic'})


@ToolRegistry.register('mt5_demo')
class MT5DemoTool(BaseTool):
    tool_id = 'mt5_demo'
    @property
    def spec(self):
        return ToolSpec(name=self.tool_id, category='mt5', timeout_seconds=55,
            description='کنترل نسخهٔ سه‌نمادی دمو خورشید برای XAUUSD، EURUSD و USDJPY. برای پرسش «داری ترید می‌کنی؟» فقط status اجرا کن. start فقط با درخواست صریح شروع؛ stop فقط با درخواست توقف. هر نماد را جدا گزارش کن. روشن بودن پردازش، داشتن پوزیشن و سودده بودن سه موضوع متفاوت‌اند. اگر داده تازه نیست وضعیت را نامشخص اعلام کن. شروع تضمین بازشدن معامله نیست. آمار ابزار و نام مدل جزو پاسخ معاملاتی نیستند.',
            parameters={'type':'object','properties':{'action':{'type':'string','enum':['start','stop','status','report','catalog']}},'required':['action']})
    def execute(self, **p):
        try:
            action = p.get('action')
            if action == 'catalog':
                from ultimate_khorshid.tools.demo_lab import CATALOG, RULES
                out={'strategies':CATALOG,'rules':RULES,'scope':'three_symbol_demo',
                     'summary':'۱۰ فرضیهٔ استراتژی؛ وجود آن‌ها به معنی سودده‌بودن اثبات‌شده نیست.'}
            else: out=portfolio_action(action)
            return ToolResult(tool_name=self.tool_id, content=json.dumps(out,ensure_ascii=False),
                              metadata=out, success=not bool(out.get('error')))
        except (ValueError,OSError) as exc:
            return ToolResult(tool_name=self.tool_id,content=str(exc),success=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['start','stop','status','report','catalog']); args=p.parse_args()
    r=MT5DemoTool().execute(action=args.action)
    print(json.dumps(r.metadata,ensure_ascii=False,indent=2) if r.success else r.content)
    return 0 if r.success else 1
if __name__=='__main__': raise SystemExit(main())
