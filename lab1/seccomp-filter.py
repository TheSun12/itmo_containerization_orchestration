import pyseccomp as seccomp
import os
import sys


f = seccomp.SyscallFilter(defaction=seccomp.ALLOW)

f.add_rule(seccomp.ERRNO(1), "chmod")
f.add_rule(seccomp.ERRNO(1), "fchmod")
f.add_rule(seccomp.ERRNO(1), "fchmodat")

f.load()

os.execv(sys.executable, [sys.executable, 'api.py'])