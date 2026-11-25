from datetime import datetime
import inspect

# Define colors for each log level
class LogColor:
    DEBUG = '\033[36m'  # Cyan
    INFO = '\033[32m'  # Green
    WARNING = '\033[33m'  # Yellow
    ERROR = '\033[31m'  # Red
    RESET = '\033[0m'  # Reset color

class Logger:
    def __init__(self, log_file):
        self.log_file = log_file
        self.log_levels = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40}
        self.current_level = 10  # Debug level

    def _format_message(self, level, message, func_name):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
        return f"{timestamp} - {level} - {message} - [{func_name}]", f"{level} - {message} - [{func_name}]"

    def _write_to_file(self, formatted_message):
        with open(self.log_file, 'a') as f:
            f.write(formatted_message + '\n')

    def _print_to_console(self, level, formatted_message):
        color = getattr(LogColor, level)
        print(f"{color}{formatted_message}{LogColor.RESET}")

    def _log(self, level, message):
        if self.log_levels[level] >= self.current_level:
            caller_frame = inspect.currentframe().f_back.f_back.f_back
            func_name = caller_frame.f_code.co_name
            formatted_message_file, formatted_message_console = self._format_message(level, message, func_name)
            self._write_to_file(formatted_message_file)
            self._print_to_console(level, formatted_message_console)

    def debug(self, message):
        self._log('DEBUG', message)

    def info(self, message):
        self._log('INFO', message)

    def warning(self, message):
        self._log('WARNING', message)

    def error(self, message):
        self._log('ERROR', message)


def setup_logger(log_file):
    return Logger(log_file)

# Setup the default logger
logger = setup_logger("application.log")

def log_message(message: str, level: str = 'debug'):
    """
    Log a message with the given level.
    
    :param level: The level of the message (debug, info, warning, error)
    :param message: The message to log
    """
    level = level.upper()
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(message)
