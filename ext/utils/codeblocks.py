"""Miscellaneous tools for creating codeblocks in discord"""
import traceback

def error_to_codeblock(error):
    """Formatting of python errors into codeblocks"""
    return f':no_entry_sign: {type(error).__name__}: {error}```py\n' \
           f'{"".join(traceback.format_exception(type(error), error, error.__traceback__))}```'
