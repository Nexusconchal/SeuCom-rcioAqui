"""Worker opcional; usa o mesmo PostgreSQL e configurações da aplicação web."""
import signal
import threading

from app import create_app
from campaign_queue import dispatcher
from inbox import dispatch_inbox


def main():
    app=create_app()
    if not app.config['DATABASE_URL']:
        raise RuntimeError('O worker separado precisa do mesmo PostgreSQL da aplicação web (DATABASE_URL).')
    stopped=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopped.set())
    signal.signal(signal.SIGINT,lambda *_:stopped.set())
    while not stopped.is_set():
        try:
            dispatcher(app,limit=1)
            if not stopped.is_set():
                dispatch_inbox(app,limit=1)
        except Exception:
            app.logger.error('Falha no processamento da fila; próxima rodada em 60 segundos.')
        stopped.wait(5)


if __name__=='__main__':
    main()
