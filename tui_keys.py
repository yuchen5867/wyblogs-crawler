"""
wyblogs 爬虫 - TUI 底层按键与用户输入监听器
支持方向键 (UP/DOWN/LEFT/RIGHT)、空格 (SPACE)、回车 (ENTER)、ESC、翻页键与快捷键无延迟捕获
"""
import sys

def get_key() -> str:
    """
    即时阻塞捕获单个按键输入并返回标准键名
    :return: 'UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'SPACE', 'ESC', 'PAGE_UP', 'PAGE_DOWN', 或普通单个字符
    """
    if sys.platform.startswith("win"):
        import msvcrt
        try:
            ch = msvcrt.getwch()
        except (KeyboardInterrupt, EOFError):
            return "CTRL_C"
        except Exception:
            return ""

        if ch in ('\x00', '\xe0'):
            try:
                ch2 = msvcrt.getwch()
            except Exception:
                return ""
            mapping = {
                'H': 'UP',
                'P': 'DOWN',
                'K': 'LEFT',
                'M': 'RIGHT',
                'I': 'PAGE_UP',
                'Q': 'PAGE_DOWN',
                'G': 'HOME',
                'O': 'END',
                'S': 'DELETE',
            }
            return mapping.get(ch2, f"SPECIAL_{ch2}")

        if ch == '\r' or ch == '\n':
            return 'ENTER'
        elif ch == ' ':
            return 'SPACE'
        elif ch == '\x1b':
            return 'ESC'
        elif ch == '\x08':
            return 'BACKSPACE'
        elif ch == '\x03':
            return 'CTRL_C'
        elif ch == '\t':
            return 'TAB'
        return ch
    else:
        # Unix / Linux / macOS fallback
        import tty
        import termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                # Escape sequence
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    seq_map = {
                        'A': 'UP',
                        'B': 'DOWN',
                        'C': 'RIGHT',
                        'D': 'LEFT',
                        '5': 'PAGE_UP',
                        '6': 'PAGE_DOWN'
                    }
                    return seq_map.get(ch3, 'ESC')
                return 'ESC'
            elif ch in ('\r', '\n'):
                return 'ENTER'
            elif ch == ' ':
                return 'SPACE'
            elif ch == '\x03':
                return 'CTRL_C'
            return ch
        except Exception:
            return ""
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
