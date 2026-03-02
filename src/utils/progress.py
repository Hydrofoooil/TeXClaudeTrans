import sys


class _LinePrinter:
    _last_len = 0
    _active = False

    @classmethod
    def update(cls, message):
        text = "" if message is None else str(message)
        pad = max(0, cls._last_len - len(text))
        sys.stdout.write("\r" + text + (" " * pad))
        sys.stdout.flush()
        cls._last_len = len(text)
        cls._active = True

    @classmethod
    def finish(cls):
        if cls._active:
            sys.stdout.write("\n")
            sys.stdout.flush()
        cls._last_len = 0
        cls._active = False


class _ProgressBar:
    def __init__(self, value=0):
        self.value = value

    def progress(self, value, text=None):
        self.value = value
        ratio = value
        if isinstance(value, (int, float)):
            if value > 1:
                ratio = value / 100.0
            ratio = max(0.0, min(1.0, float(ratio)))
            width = 24
            filled = int(width * ratio)
            bar = "[" + ("#" * filled) + ("-" * (width - filled)) + "]"
            percent = f"{ratio * 100:5.1f}%"
            msg = f"{bar} {percent}"
            if text:
                msg = f"{msg} {text}"
            _LinePrinter.update(msg)
        elif text:
            _LinePrinter.update(text)
        return self


class _Status:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def text(self, message):
        _LinePrinter.update(message)

    def success(self, message):
        _LinePrinter.finish()
        print(message)

    def error(self, message):
        _LinePrinter.finish()
        print(message)

    def progress(self, value=0, text=None):
        bar = _ProgressBar(value=value)
        if text:
            _LinePrinter.update(text)
        return bar

    def empty(self):
        _LinePrinter.finish()
        return None


class _CliProgress:
    @staticmethod
    def empty():
        return _Status()

    @staticmethod
    def progress(value=0, text=None):
        bar = _ProgressBar(value=value)
        if text:
            _LinePrinter.update(text)
        return bar

    @staticmethod
    def success(message):
        _LinePrinter.finish()
        print(message)

    @staticmethod
    def error(message):
        _LinePrinter.finish()
        print(message)


st = _CliProgress()
