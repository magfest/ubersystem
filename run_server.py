from __future__ import unicode_literals

import traceback
import sys
import os
def trace_residue(frame, event, arg):
    if event == 'call':
        code = frame.f_code
        filename = code.co_filename
        # Only log if the call is inside the residue package
        if 'site-packages/residue' in filename:
            func_name = code.co_name
            line_no = frame.f_lineno
            print(f"[RESIDUE CALL] {filename}:{line_no} -> {func_name}")
            traceback.print_exc()
            print()
    return trace_residue

# Start tracing
sys.settrace(trace_residue)

import cherrypy

import uber.server

if __name__ == '__main__':
    cherrypy.engine.start()
    cherrypy.engine.block()
