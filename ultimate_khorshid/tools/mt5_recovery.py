"""Restart reconciliation for the existing DEMO worker; no broker operations."""


class Recovery:
    def __init__(self, snapshot):
        self.instance = snapshot.get('executor_instance')
        self.waiting_since = None
        self.blocked_entry_bar = None

    def unavailable(self, now):
        first = self.waiting_since is None
        if first:
            self.waiting_since = now
        return first

    def observe(self, snapshot):
        instance = snapshot.get('executor_instance')
        if self.instance is not None and instance is None:
            raise ValueError('Executor lost restart identity; refusing protocol downgrade')
        restarted = instance is not None and instance != self.instance
        recovered = self.waiting_since is not None or restarted
        self.instance = instance
        if recovered:
            self.blocked_entry_bar = snapshot['bars'][-1]['time']
            self.waiting_since = None
        return recovered

    def constrain(self, plan, bar):
        if self.blocked_entry_bar is not None:
            if bar > self.blocked_entry_bar:
                self.blocked_entry_bar = None
            elif plan.get('action') == 'open':
                return {'status':'waiting_for_next_bar',
                        'reason':'Reconnected; existing positions reconciled; wait for a fresh entry candle'}
        return plan


def lease_text(snapshot, run_id, now):
    values = [int(now), snapshot['login'], run_id, snapshot['symbol'], snapshot['period']]
    instance = snapshot.get('executor_instance')
    if instance is not None:
        if not isinstance(instance, str) or not instance or len(instance) > 128:
            raise ValueError('Invalid executor instance')
        values.append(instance)
    if any('\t' in str(value) or '\n' in str(value) or '\r' in str(value) for value in values):
        raise ValueError('Invalid execution lease field')
    return '\t'.join(map(str, values)) + '\n'
