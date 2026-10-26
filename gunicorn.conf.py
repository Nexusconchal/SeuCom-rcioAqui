"""Allow the inbox delivery loop to finish its current provider request on shutdown."""

# Do not log raw URLs/referrers: tracking and webhook paths contain credentials.
access_log_format = '%(h)s %(t)s "%(m)s %({sca.log_route}e)s %(H)s" %(s)s %(b)s %(L)s'


def worker_exit(server, worker):
    app = getattr(worker, 'wsgi', None)
    extensions = getattr(app, 'extensions', {})
    stopped = extensions.get('inbox_dispatch_stop')
    if stopped is not None:
        stopped.set()
    thread = extensions.get('inbox_dispatch_thread')
    if thread is not None:
        thread.join(timeout=20)
