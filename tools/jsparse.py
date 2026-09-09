"""Minimal parser for the minified JS object-literal subset used by the docs registry."""
import re

NUM = re.compile(r'-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
KW = re.compile(r'null|true|false|undefined|void 0')
IDENT = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')
KEY = re.compile(r'[A-Za-z0-9_$]+')

ESC = {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f', 'v': '\v', '0': '\0'}


class P:
    def __init__(self, s, i=0):
        self.s = s
        self.i = i

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in ' \t\r\n':
            self.i += 1

    def value(self):
        v = self.value_head()
        while self.s.startswith('.join(', self.i):
            self.i += 6
            sep = self.value_head()
            self.ws()
            assert self.s[self.i] == ')'
            self.i += 1
            if isinstance(v, list):
                v = (sep if isinstance(sep, str) else '').join(str(x) for x in v)
        return v

    def value_head(self):
        self.ws()
        c = self.s[self.i]
        if c == '{':
            return self.obj()
        if c == '[':
            return self.arr()
        if c in '`"\'':
            return self.string()
        if c == '!':
            self.i += 1
            d = self.s[self.i]
            self.i += 1
            return d == '0'
        m = KW.match(self.s, self.i)
        if m:
            self.i = m.end()
            return {'true': True, 'false': False}.get(m.group(), None)
        m = NUM.match(self.s, self.i)
        if m:
            self.i = m.end()
            t = m.group()
            return float(t) if ('.' in t or 'e' in t.lower()) else int(t)
        m = IDENT.match(self.s, self.i)
        if m:
            self.i = m.end()
            return {'__ref__': m.group()}
        raise ValueError('unexpected %r at %d: %r' % (c, self.i, self.s[self.i:self.i + 60]))

    def string(self):
        q = self.s[self.i]
        self.i += 1
        out = []
        while True:
            c = self.s[self.i]
            if c == '\\':
                nxt = self.s[self.i + 1]
                if nxt == 'u':
                    if self.s[self.i + 2] == '{':
                        e = self.s.index('}', self.i)
                        out.append(chr(int(self.s[self.i + 3:e], 16)))
                        self.i = e + 1
                        continue
                    out.append(chr(int(self.s[self.i + 2:self.i + 6], 16)))
                    self.i += 6
                    continue
                if nxt == 'x':
                    out.append(chr(int(self.s[self.i + 2:self.i + 4], 16)))
                    self.i += 4
                    continue
                if nxt == '\n':
                    self.i += 2
                    continue
                out.append(ESC.get(nxt, nxt))
                self.i += 2
                continue
            if c == q:
                self.i += 1
                return ''.join(out)
            out.append(c)
            self.i += 1

    def skip_expr(self):
        """Consume an arbitrary JS expression up to a top-level ',' or closing bracket."""
        start = self.i
        depth = 0
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in '`"\'':
                self.string()
                continue
            if c in '([{':
                depth += 1
            elif c in ')]}':
                if depth == 0:
                    break
                depth -= 1
            elif c == ',' and depth == 0:
                break
            self.i += 1
        return self.s[start:self.i]

    def obj(self):
        self.i += 1
        d = {}
        self.ws()
        if self.s[self.i] == '}':
            self.i += 1
            return d
        while True:
            self.ws()
            c = self.s[self.i]
            if c in '`"\'':
                k = self.string()
            elif c == '[':
                self.i += 1
                k = self.value()
                self.ws()
                assert self.s[self.i] == ']'
                self.i += 1
            else:
                m = KEY.match(self.s, self.i)
                k = m.group()
                self.i = m.end()
            self.ws()
            assert self.s[self.i] == ':', (k, self.s[self.i:self.i + 40])
            self.i += 1
            d[k] = self.value()
            self.ws()
            if self.s[self.i] == ',':
                self.i += 1
                self.ws()
            if self.s[self.i] == '}':
                self.i += 1
                return d

    def arr(self):
        self.i += 1
        a = []
        self.ws()
        if self.s[self.i] == ']':
            self.i += 1
            return a
        while True:
            self.ws()
            if self.s.startswith('...', self.i):
                a.append({'__spread__': self.skip_expr()})
            else:
                a.append(self.value())
            self.ws()
            if self.s[self.i] == ',':
                self.i += 1
                self.ws()
            if self.s[self.i] == ']':
                self.i += 1
                return a


def parse_at(s, i):
    p = P(s, i)
    return p.value(), p.i
