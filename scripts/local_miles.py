"""Collect local mileage offers, send configured alerts, and publish encrypted data."""
import argparse
import asyncio
import getpass
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values, load_dotenv, set_key


def normalize_chat(value):
    value = value.strip()
    link = re.search(r"(?:https://)?t\.me/c/(\d+)(?:/|$)", value)
    if link:
        return "-100" + link.group(1)
    if re.fullmatch(r"-?\d+", value):
        return value
    raise ValueError("Use o ID do grupo ou um link de mensagem no formato t.me/c/...")


def configure():
    values = dotenv_values(ROOT / ".env")
    print("Configuração local de milhas. Os dados ficam no .env deste PC, fora do Git.")
    if not re.fullmatch(r"\d+:[\w-]{30,}", values.get("TELEGRAM_BOT_TOKEN") or ""):
        token = getpass.getpass("Token do bot Telegram: ").strip()
        if not re.fullmatch(r"\d+:[\w-]{30,}", token):
            raise ValueError("Formato de token inválido.")
        set_key(ROOT / ".env", "TELEGRAM_BOT_TOKEN", token)
    chat = input("ID do grupo Telegram ou link de uma mensagem (Enter mantém o valor atual): ")
    if chat.strip():
        set_key(ROOT / ".env", "TELEGRAM_CHANNEL_ID", normalize_chat(chat))
    password = getpass.getpass("Senha atual do painel (Enter mantém o valor atual): ")
    if password:
        set_key(ROOT / ".env", "PANEL_PASSWORD", password)
    print("Configuração salva. Use Rodar-Milhas.cmd para executar agora.")


class SingleRun:
    """Manual and scheduled executions share the same process lock."""
    def __enter__(self):
        (ROOT / "data").mkdir(exist_ok=True)
        self.file = (ROOT / "data/local-miles.lock").open("a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Já existe uma consulta de milhas em execução.") from None
        return self

    def __exit__(self, *args):
        self.file.close()


async def local_sender(offer, previous, topic):
    # Use the installed local transport here too: the ISP may reject the
    # Telegram library's default handshake even when the native client works.
    import config
    from miles.cycle import NAMES
    from miles.transport import Client
    text = (f"✈️ BAIXOU EM MILHAS · {NAMES[offer.airline]}\n\n"
            f"{offer.origin} → {offer.destination}\nIda: {offer.departure_date}"
            + (f" · volta: {offer.return_date}" if offer.return_date else " · por trecho")
            + f"\nDe {previous:,} para {offer.points:,} pontos/milhas\n"
            f"{offer.condition} · {offer.cabin}\n\n"
            "Oferta publicada; confirme disponibilidade e taxas antes de emitir.\n" + offer.url)
    payload = {"chat_id": config.TELEGRAM_CHANNEL_ID, "text": text}
    if topic is not None:
        payload["message_thread_id"] = topic
    try:
        response = await asyncio.to_thread(Client(timeout=15).post,
            "https://api.telegram.org/bot" + config.TELEGRAM_BOT_TOKEN + "/sendMessage", json=payload)
        return response.status_code == 200 and response.json().get("ok") is True
    except Exception as exc:
        logging.warning("Envio local falhou (%s); próxima coleta tentará novamente.", type(exc).__name__)
        return False


async def collect(scheduled=False, short=False):
    from miles.cycle import run
    from scripts.miles_publication import publish
    marker = ROOT / "data/local-miles-last-run.txt"
    now = datetime.now(timezone.utc)
    if scheduled and marker.exists():
        try:
            last = datetime.fromisoformat(marker.read_text().strip())
            if now - last < timedelta(minutes=30):
                logging.info("Uma coleta recente já terminou; execução automática dispensada.")
                return 0
        except ValueError:
            pass
    notify = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHANNEL_ID"))
    if not notify:
        logging.warning("Destino Telegram não configurado. Coleta segue; execute Configurar-Milhas.cmd para ativar alertas.")
    brt = now.astimezone(ZoneInfo("America/Sao_Paulo"))
    report = await run(include_far=not short and (not scheduled or brt.hour < 14),
                       notify=notify, sender=local_sender)
    if all(p["status"] == "error" for p in report["programs"].values()):
        logging.error("Todas as fontes falharam. Consulte logs/local-miles.log e tente novamente.")
        return 1
    marker.write_text(datetime.now(timezone.utc).isoformat())
    password = os.environ.get("PANEL_PASSWORD")
    if password:
        try:
            await asyncio.to_thread(publish, password, ROOT)
        except Exception as exc:
            # These publication messages contain no credentials or private source names.
            logging.warning("%s", str(exc))
            return 2
    else:
        logging.warning("Senha do painel não configurada. Dados ficam locais; execute Configurar-Milhas.cmd para publicar.")
    logging.info("Coleta local concluída.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--short", action="store_true", help="Use the 14h/20h date window")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.configure:
        configure()
        return 0
    if args.interactive:
        values = dotenv_values(ROOT / ".env")
        if not values.get("TELEGRAM_CHANNEL_ID") or not values.get("PANEL_PASSWORD"):
            configure()
    load_dotenv(ROOT / ".env", override=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    handlers = [RotatingFileHandler(ROOT / "logs/local-miles.log",
                    maxBytes=2_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=handlers)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with SingleRun():
        return asyncio.run(collect(args.scheduled, args.short))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.error("Execução local interrompida (%s).", type(exc).__name__)
        print(f"Execução local interrompida ({type(exc).__name__}). Consulte logs/local-miles.log.", file=sys.stderr)
        raise SystemExit(1) from None
