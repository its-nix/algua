# Proposed wheel URL identity: field-level contract

Status: proposed, not normative. See [SPEC.md](SPEC.md) for the approval condition. Baseline:
`db6860000f87a6cc98469e0e4901fa9c10c0d277`. Source references are `path:line` at that baseline.

Unless a row is marked as changed, this document describes **existing** behavior of
`algua/registry/planner_environment_lock.py` that must stay byte-for-byte equivalent. The only
proposed behavior change is step 5a below: how a validated IPv6 address is spelled.

Draft provenance: preserved Claude-authored proposal from the preparation worktree, adopted and
source-checked in task `t_7183feee`. Literal vectors below are proposed acceptance expectations,
not a claim that protected implementation exists. Fresh documentation-sketch probes are recorded
in that task's handoff; upstream probes are not silently treated as fresh evidence. Product
red/green tests, mutation checks and full dual-interpreter acceptance remain future work.

## 1. Function contract

`wheel_url_identity(url: str) -> str` at `planner_environment_lock.py:115` validates one URL and
returns its canonical ownership identity, or raises `EnvironmentIncompatible`. The steps run in the
order below and the first failure wins. Every failure is `EnvironmentIncompatible` with the listed
message. Formatting cannot raise, so the proposed change does not move any failure.

| # | Field | Rule | Source |
|---|---|---|---|
| 1 | Characters | Refuse an empty string or any character outside ASCII letters, digits and `-._~:/?#[]@!$&'()*+,;=%`. Runs before any case folding, so KELVIN SIGN cannot lowercase into an ASCII host. | `:128` |
| 2 | Escape syntax | Refuse any `%` not followed by two hex digits, anywhere in the URL. | `:132` |
| 3 | Split and scheme | `_URL.fullmatch` splits `scheme://authority path ?query`. No match, or a scheme that is not `https` case-insensitively, is refused. `#` is consumable by no group, so any fragment, even an empty one, fails here. | `:134` |
| 4 | Authority | Dispatch: `_IP_LITERAL.fullmatch` commits to the IPv6 branch (5); otherwise `_REG_NAME.fullmatch` commits to the name branch (6); neither is an invalid authority. | `:99` |
| 5 | IPv6 branch | Address text must fit `[0-9A-Fa-f:.]+`, so a zone (`%`) or IPvFuture cannot match. `ipaddress.IPv6Address` validates it, and `ValueError` becomes the IPv6 refusal. **Address is validated before the port.** | `:100` |
| 5a | IPv6 spelling | **Changed.** Today: `.compressed`. Proposed: section 2. | `:103` |
| 6 | Name branch | `_hostname` runs before `_port`, so a bad host outranks a bad port. See 6a and 6b. | `:108` |
| 6a | IPv4 | Host is lowercased. If its last dot-separated label matches `[0-9]+` or `0[xX][0-9A-Fa-f]*`, the whole host must be a strict `IPv4Address` (four decimal octets, no leading zeros) and is emitted as `str()`. Otherwise it is an ambiguous numeric host. Mirrors uv's WHATWG numeric-host rule. | `:71` |
| 6b | DNS | At most 253 characters; every label matches `[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?`. A trailing dot gives an empty label and fails. A single label is valid. | `:76` |
| 7 | Port | Empty or absent means default. Leading zeros are insignificant and more than five significant digits fails before integer conversion, so an arbitrarily long digit string cannot raise a raw `ValueError`. Must be 1 to 65535. `443` is omitted; any other port is emitted as its integer. | `:81` |
| 8 | Path and query syntax | Path must match `[pchar/]*`, query `[pchar/?]*`. Only `[` and `]` can reach this refusal; the grammar has already consumed `?` and `#`. | `:139` |
| 9 | Path escapes | `_normalize_escapes`: an escape of an unreserved character decodes; every other escape stays, with uppercase hex. `%25` is never decoded, so normalization cannot manufacture a new escape. | `:43` |
| 10 | Dot segments | `_remove_dot_segments` runs after escape normalization, so `%2E%2E` is a dot segment. `..` cannot pop the root. A trailing dot segment leaves a trailing `/`. Empty segments are kept. | `:52` |
| 11 | Wheel name | The last normalized segment must be longer than four characters and end in the case-sensitive `.whl`. | `:142` |
| 12 | Assembly | `https://` + authority + normalized path, then `?` + escape-normalized query if a query was present. An empty query is kept as `?`. The query keeps its order and case and gets no dot-segment removal. | `:145` |

Scheme and host are the only case-folded parts. Path and query case are significant.

## 2. Proposed IPv6 identity algorithm

Input is the `IPv6Address` already validated in step 5. No text rendering of that object is used:
not `str()`, `.compressed` or `.exploded`.

1. Take the 128-bit value as its 16 big-endian `packed` bytes, or equivalently `int(address)`.
2. Form eight unsigned 16-bit groups, most significant first.
3. Render each group as minimal lowercase hexadecimal, with zero rendered `0`.
4. Find the longest run of consecutive zero groups. Ties go to the leftmost run.
5. If that run has length 2 or more, replace it with `::`, which gives `::x`, `x::` or `::` for a
   leading, trailing or all-zero run. A run of length 1 or 0 is not compressed.
6. Otherwise join all eight groups with `:`.

The output never contains a dot, is a valid `IPv6Address` input and parses to the same 128-bit
value, so applying the algorithm to its own output is the identity function.

Reference sketch, not binding on the implementation:

```python
def _ipv6_identity(address: ipaddress.IPv6Address) -> str:
    packed = address.packed
    groups = [int.from_bytes(packed[i:i + 2], "big") for i in range(0, 16, 2)]
    start, length, index = -1, 0, 0
    while index < 8:
        end = index
        while end < 8 and groups[end] == 0:
            end += 1
        if end - index > length:
            start, length = index, end - index
        index = max(end, index + 1)
    hextets = [format(group, "x") for group in groups]
    if length < 2:
        return ":".join(hextets)
    return f"{':'.join(hextets[:start])}::{':'.join(hextets[start + length:])}"
```

Call site: `host = f"[{_ipv6_identity(ipaddress.IPv6Address(literal['address']))}]"`, inside the
existing `try` at `:102`, with `_port` still afterwards at `:106`.

### Equivalence to today's output

`_compress_hextets` has the same body in both installed stdlibs, with the same `> 1` threshold and
strict `>` that keeps the leftmost tie. The divergence comes only from 3.12.12's
`IPv6Address.__str__`, which routes `self.ipv4_mapped is not None`, meaning `(ip >> 32) == 0xFFFF`,
through a dotted formatter. Therefore:

- for every address, the proposed output equals what 3.12.3's `.compressed` returns today;
- for every address outside `::ffff:0:0/96`, it also equals what 3.12.12's `.compressed` returns;
- inside `::ffff:0:0/96`, 3.12.12's output changes from dotted to all-hex, which restores the golden.

### Parser delta between the two interpreters

3.12.12 also changed the parser: `_ip_int_from_string` refuses `len(ip_str) > 45` and splits with
`maxsplit=9`. `_parse_hextet`, `_parse_octet` and the IPv4 parser are textually identical at the
lines compared. The source trace predicts no accepted-language change:

- The longest valid literal is `x:x:x:x:x:x:ddd.ddd.ddd.ddd`: 24 hex digits, 6 colons and a 15
  character suffix, exactly 45 characters. Hextets are at most 4 characters and octets at most 3
  with no leading zeros, and `::` forms are shorter. So every string over 45 characters was already
  invalid on 3.12.3.
- A string with ten or more colon-separated parts fails on both: too many parts, or a remainder
  containing `:` handed to `IPv4Address`.
- The two parsers differ only in `AddressValueError` text, which step 5 collapses into one message.

The boundary vectors in sections 3 and 4 pin this. If either disagrees between interpreters, that
is a stop condition in the SPEC, not something to patch here.

## 3. Accepted vectors

Each row is `input → identity` and must hold on both interpreters. Each output, fed back as input,
must return itself.

### Mapped equivalents, all `https://[::ffff:c000:20a]/x.whl`

| Spelling | Input |
|---|---|
| Existing golden, mixed uppercase (*probed*: holds on 3.12.3, fails on 3.12.12 today) | `https://[::FFFF:192.0.2.10]/x.whl` |
| Mixed lowercase | `https://[::ffff:192.0.2.10]/x.whl` |
| Hex, already the identity | `https://[::ffff:c000:20a]/x.whl` |
| Hex uppercase, padded | `https://[::FFFF:C000:020A]/x.whl` |
| Expanded hex | `https://[0:0:0:0:0:ffff:c000:20a]/x.whl` |
| Fully padded hex | `https://[0000:0000:0000:0000:0000:ffff:c000:020a]/x.whl` |
| Expanded mixed | `https://[0:0:0:0:0:FFFF:192.0.2.10]/x.whl` |
| Fully padded mixed, 3.12.12's `.exploded` | `https://[0000:0000:0000:0000:0000:ffff:192.0.2.10]/x.whl` |

### Mapped boundaries

| Input | Identity |
|---|---|
| `https://[::ffff:0.0.0.0]/x.whl` | `https://[::ffff:0:0]/x.whl` |
| `https://[::ffff:0.0.0.1]/x.whl` | `https://[::ffff:0:1]/x.whl` |
| `https://[::ffff:0.1.0.0]/x.whl` | `https://[::ffff:1:0]/x.whl` |
| `https://[::ffff:255.255.255.255]/x.whl` | `https://[::ffff:ffff:ffff]/x.whl` |
| `https://[0000:0000:0000:0000:0000:ffff:255.255.255.255]/x.whl` (exactly 45 characters) | `https://[::ffff:ffff:ffff]/x.whl` |

### Dotted input that is not mapped

| Input | Identity |
|---|---|
| `https://[::192.0.2.10]/x.whl` | `https://[::c000:20a]/x.whl` |
| `https://[64:ff9b::192.0.2.10]/x.whl` | `https://[64:ff9b::c000:20a]/x.whl` |
| `https://[::ffff:0:192.0.2.10]/x.whl` | `https://[::ffff:0:c000:20a]/x.whl` |

### Compression

| Case | Input | Identity |
|---|---|---|
| All zero | `https://[0:0:0:0:0:0:0:0]/x.whl` | `https://[::]/x.whl` |
| All zero, padded | `https://[0000:0000:0000:0000:0000:0000:0000:0000]/x.whl` | `https://[::]/x.whl` |
| All zero, idempotent | `https://[::]/x.whl` | `https://[::]/x.whl` |
| Loopback | `https://[0:0:0:0:0:0:0:1]/x.whl` | `https://[::1]/x.whl` |
| Leading run | `https://[0:0:0:1:2:3:4:5]/x.whl` | `https://[::1:2:3:4:5]/x.whl` |
| Trailing run | `https://[1:2:3:4:5:0:0:0]/x.whl` | `https://[1:2:3:4:5::]/x.whl` |
| Trailing run of seven | `https://[1:0:0:0:0:0:0:0]/x.whl` | `https://[1::]/x.whl` |
| Run of exactly two | `https://[1:0:0:2:3:4:5:6]/x.whl` | `https://[1::2:3:4:5:6]/x.whl` |
| Tie, leftmost wins | `https://[1:0:0:2:3:0:0:4]/x.whl` | `https://[1::2:3:0:0:4]/x.whl` |
| Tie with a trailing run | `https://[1:0:0:2:3:4:0:0]/x.whl` | `https://[1::2:3:4:0:0]/x.whl` |
| Longest beats leftmost | `https://[1:0:0:2:0:0:0:3]/x.whl` | `https://[1:0:0:2::3]/x.whl` |
| Singleton not compressed | `https://[1:0:2:3:4:5:6:7]/x.whl` | `https://[1:0:2:3:4:5:6:7]/x.whl` |
| `::` covering a leading singleton | `https://[::1:2:3:4:5:6:7]/x.whl` | `https://[0:1:2:3:4:5:6:7]/x.whl` |
| `::` covering a trailing singleton | `https://[1:2:3:4:5:6:7::]/x.whl` | `https://[1:2:3:4:5:6:7:0]/x.whl` |
| `::` covering an interior singleton | `https://[1:2:3::4:5:6:7]/x.whl` | `https://[1:2:3:0:4:5:6:7]/x.whl` |
| Case and padding | `https://[2001:0DB8::ABCD]/x.whl` | `https://[2001:db8::abcd]/x.whl` |

### Case, ports, escapes and dots

| Case | Input | Identity |
|---|---|---|
| Scheme case and default port | `HTTPS://[::FFFF:192.0.2.10]:443/x.whl` | `https://[::ffff:c000:20a]/x.whl` |
| Empty port | `https://[::ffff:192.0.2.10]:/x.whl` | `https://[::ffff:c000:20a]/x.whl` |
| Padded default port | `https://[::ffff:192.0.2.10]:0443/x.whl` | `https://[::ffff:c000:20a]/x.whl` |
| Non-default port | `https://[::ffff:192.0.2.10]:8443/x.whl` | `https://[::ffff:c000:20a]:8443/x.whl` |
| Padded non-default port | `https://[::ffff:192.0.2.10]:08443/x.whl` | `https://[::ffff:c000:20a]:8443/x.whl` |
| Existing IPv6 golden | `https://[2001:DB8:0:0:0:0:0:1]:8443/x.whl` | `https://[2001:db8::1]:8443/x.whl` |
| Escapes and dots on an IPv6 host | `https://[::ffff:192.0.2.10]/a/./b/../%78%2ewhl` | `https://[::ffff:c000:20a]/a/x.whl` |
| Reserved stays escaped, query normalized | `https://files.pythonhosted.org/x%2bcpu.whl?q=%7e%2f` | `https://files.pythonhosted.org/x%2Bcpu.whl?q=~%2F` |
| No dot removal in a query | `https://files.pythonhosted.org/x.whl?p=/a/../b` | `https://files.pythonhosted.org/x.whl?p=/a/../b` |
| IPv4 default port | `https://192.0.2.10:443/x.whl` | `https://192.0.2.10/x.whl` |

All 20 existing `WHEEL_URL_IDENTITIES` entries in `tests/test_planner_environment_lock.py:162` stay
unchanged. They are the preservation baseline for the rest of the grammar.

## 4. Rejection matrix

This is unchanged behavior. Every row raises `EnvironmentIncompatible` with the exact message;
assert `str(exc.value) == expected_message` (an unanchored `match=` regex is not an exact assertion).
Existing tests assert only the class, so this tightens the assertion without changing behavior.
The "order" rows prove which check wins when two would fail.

| Message (after `locked wheel URL `) | Input | Why |
|---|---|---|
| `contains a character a URL cannot carry` | `""` | empty |
| same | `https://files.pythonhosted.org/x y.whl` | space |
| same | `https://files.pythonhosted.org/café.whl` | non-ASCII |
| same | `https://Keras.org/x.whl` | KELVIN SIGN, before folding |
| same | `https://files.pythonhosted.org/a\\x.whl` | backslash |
| `has a malformed percent escape` | `https://files.pythonhosted.org/x%2.whl` | short escape |
| same | `https://files.pythonhosted.org/x.whl?v=%g1` | query escape |
| same | `https://[fe80::1%eth0]/x.whl` | scoped, bare `%` |
| `is not an HTTPS URL` | `http://files.pythonhosted.org/x.whl` | scheme |
| same | `https:files.pythonhosted.org/x.whl` | no authority marker |
| same | `https://files.pythonhosted.org/x.whl#sha256=abc` | fragment |
| same | `https://files.pythonhosted.org/x.whl#` | empty fragment |
| `authority is invalid` | `https:///x.whl` | empty host |
| same | `https://:443/x.whl` | port only |
| same | `https://::1/x.whl` | unbracketed IPv6 |
| same | `https://[::1/x.whl` | unterminated literal |
| same | `https://[fe80::1%25eth0]/x.whl` | scoped, escaped zone |
| same | `https://[v1.x]/x.whl` | IPvFuture |
| same | `https://[::g]/x.whl` | non-hex fails the literal class, so this is not the IPv6 message |
| same | `https://[not-an-ip]/x.whl` | same class failure |
| same | `https://user:secret@files.pythonhosted.org/x.whl` | password credentials |
| same | `https://user@[::1]/x.whl` | credentials on an IPv6 host |
| same | `https://files.pythonhosted.org:https/x.whl` | non-numeric port |
| same | `https://[::1]:abc/x.whl` | non-numeric port on IPv6 |
| `IPv6 address is invalid` | `https://[::ffff:192.0.2.256]/x.whl` | octet out of range |
| same | `https://[::ffff:01.2.3.4]/x.whl` | octet leading zero |
| same | `https://[12345::]/x.whl` | hextet too long |
| same | `https://[1::2::3]/x.whl` | two `::` |
| same | `https://[1:2:3:4:5:6:7:8:9]/x.whl` | nine groups |
| same | `https://[192.0.2.10]/x.whl` | bare IPv4 in brackets |
| same | `https://[0000:0000:0000:0000:0000:ffff:255.255.255.2555]/x.whl` | 46 characters; both parsers refuse, with different internal reasons |
| same | `https://[0000:0000:0000:0000:0000:0000:0000:0000:0000:0000]/x.whl` | ten groups, over 45 characters |
| same (order: address before port) | `https://[1::2::3]:0/x.whl` | not the port message |
| `has an ambiguous numeric host` | `https://01.2.3.4/x.whl` | leading zero |
| same | `https://1.2.3/x.whl` | short |
| same | `https://0x7f.0.0.1/x.whl` | hex |
| same | `https://16909060/x.whl` | integer |
| same | `https://example.0x/x.whl` | numeric last label |
| same | `https://user@192.0.2.10/x.whl` | credentials before a numeric last label |
| same (order: host before port) | `https://01.2.3.4:0/x.whl` | not the port message |
| `hostname is invalid` | `https://user@files.pythonhosted.org/x.whl` | userinfo reaches the DNS label check |
| same | `https://@files.pythonhosted.org/x.whl` | empty userinfo |
| same | `https://files_python.org/x.whl` | underscore |
| same | `https://files..pythonhosted.org/x.whl` | empty label |
| same | `https://-files.pythonhosted.org/x.whl` | hyphen edge |
| same | `https://files.pythonhosted.org./x.whl` | trailing dot |
| same | `https://files%2Epythonhosted.org/x.whl` | escaped host |
| `port is invalid` | `https://files.pythonhosted.org:0/x.whl` | zero |
| same | `https://files.pythonhosted.org:65536/x.whl` | above range |
| same | `https://files.pythonhosted.org:99999999999/x.whl` | too many digits |
| same | `https://[::ffff:192.0.2.10]:0/x.whl` | zero on IPv6 |
| same | `https://[::ffff:192.0.2.10]:65536/x.whl` | above range on IPv6 |
| `path or query is invalid` | `https://files.pythonhosted.org/[x].whl` | bracket in path |
| same | `https://files.pythonhosted.org/x.whl?v=[1]` | bracket in query |
| `port is invalid` (order: authority before path) | `https://[::ffff:192.0.2.10]:0/[x].whl` | port refusal wins over path brackets |
| `does not name a wheel` | `https://files.pythonhosted.org` | no path |
| same | `https://files.pythonhosted.org/x.tar.gz` | not a wheel |
| same | `https://files.pythonhosted.org/.whl` | bare extension |
| same | `https://files.pythonhosted.org/x?file=x.whl` | wheel only in query |
| same | `https://files.pythonhosted.org/x.whl%2F` | escaped slash suffix |
| same | `https://files.pythonhosted.org/x.WHL` | suffix case |
| same | `https://files.pythonhosted.org/x.whl/..` | dot segment removes the name |

Lock-level order in `locked_wheels` (`:149`) is also unchanged, per wheel: non-string URL or hash,
then `wheel_url_identity`, then the `sha256:` hash pattern, then duplicate ownership. The duplicate
check is global across the lock, so two aliases inside one package are refused too, with the same
message: `a wheel URL is locked for more than one package`.

## 5. RFC-distinct URLs

Each pair must have different identities, and a lock listing the pair under two packages must be
accepted with both exact raw keys. `H` is `https://files.pythonhosted.org`.

| Distinction | First | Second |
|---|---|---|
| Reserved escape versus raw | `H/x%2Bcpu.whl` | `H/x+cpu.whl` |
| Escaped versus real separator | `H/a%2Fb.whl` | `H/a/b.whl` |
| Query absent versus empty | `H/x.whl` | `H/x.whl?` |
| Query order | `H/x.whl?a=1&b=2` | `H/x.whl?b=2&a=1` |
| Query case | `H/x.whl?a=1` | `H/x.whl?A=1` |
| Path case | `H/x.whl` | `H/X.whl` |
| Empty path segment | `H/x.whl` | `H//x.whl` |
| Port | `https://[::ffff:c000:20a]/x.whl` | `https://[::ffff:c000:20a]:8443/x.whl` |
| IPv4 versus mapped | `https://192.0.2.10/x.whl` | `https://[::ffff:192.0.2.10]/x.whl` |
| Mapped versus compatible | `https://[::ffff:192.0.2.10]/x.whl` | `https://[::192.0.2.10]/x.whl` |
| Mapped versus translated | `https://[::ffff:192.0.2.10]/x.whl` | `https://[::ffff:0:192.0.2.10]/x.whl` |
| Different mapped address | `https://[::ffff:192.0.2.10]/x.whl` | `https://[::ffff:192.0.2.11]/x.whl` |

## 6. Duplicate ownership

Any two of the eight mapped equivalents in section 3, locked under two packages, must raise
`a wheel URL is locked for more than one package` on both interpreters. `locked_wheels` keeps each
accepted URL under its exact raw spelling; `locked_wheel_owners` keys the same owners by identity.

## 7. Outage attribution

`is_locked_wheel_outage` (`planner_environment_outage.py:74`) is not edited. Its identity-keyed
lookup at `:101-104` already gives the required behavior once the identity is invariant. Tests use
the recorded-report fixture with the URL substituted, in both directions. `W` is
`/packages/six-1.17.0-py2.py3-none-any.whl`.

| Locked URL | Reported URL | Expected |
|---|---|---|
| `https://[::FFFF:192.0.2.10]W` | `https://[::ffff:c000:20a]W` | True |
| `https://[::ffff:c000:20a]W` | `https://[::FFFF:192.0.2.10]W` | True |
| `https://[0:0:0:0:0:ffff:c000:20a]W` | `https://[::ffff:192.0.2.10]W` | True |
| `https://[::ffff:192.0.2.10]:443W` | `https://[::ffff:c000:20a]W` | True |
| `https://[::ffff:192.0.2.10]W` | `https://[::ffff:192.0.2.11]W` (unlocked) | False |
| `https://[::ffff:192.0.2.10]W` | `https://192.0.2.10W` (IPv4, a different owner) | False |
| `https://[::ffff:192.0.2.10]W` | `https://[::ffff:192.0.2.256]W` (malformed) | False |
| `https://[::ffff:192.0.2.10]W` | `https://[fe80::1%25eth0]W` (scoped) | False |
| `https://[::ffff:192.0.2.10]W` | the alias, with `six==1.17.0` swapped for `other==1.0` | False |
| `https://[::ffff:192.0.2.10]W` | the alias, with a later cause repeating a different spelling | False |
| `https://[::ffff:192.0.2.10]W` | the alias, with a hash-mismatch report | False |
| `https://[::ffff:192.0.2.10]W` | the alias, with a timeout as the final cause | False |

Report shape, the one-report rule, the cause allowlist and the temporary-failure allowlist are
unchanged. Same canonical owner never makes an otherwise unrecognized report retryable. A False
result falls through to `EnvironmentIncompatible` at `planner_environment.py:198`.

No real uv IP-literal failure report is claimed by this specification task. The alias examples
are synthetic recognizer expectations, not captured network evidence. If uv spells a URL in a
form the recognizer does not match, the outcome stays fail-closed and non-retryable, never a false
retry; broadening the recognizer would require separate review.

## 8. Entry-point and consumer inventory

### Identity core

| Function | Location | Direct production callers | Role |
|---|---|---|---|
| `wheel_url_identity` | `planner_environment_lock.py:115` | `locked_wheels:191`, `locked_wheel_owners:212`, `planner_environment_outage.py:101` | validates and derives identity |
| `locked_wheels` | `planner_environment_lock.py:149` | `validate_lock:202`, `locked_wheel_owners:212` | raw URL to owner map; identity only in the local `owners` set at `:164` |
| `validate_lock` | `planner_environment_lock.py:201` | `build_environment_key` at `planner_environment.py:115` | returns None |
| `locked_wheel_owners` | `planner_environment_lock.py:205` | `provision_environment` at `planner_environment.py:195` | identity to owner map, in memory |
| `is_locked_wheel_outage` | `planner_environment_outage.py:74` | `provision_environment` at `planner_environment.py:196` | retry classification |

### Environment seam

- `build_environment_key` (`planner_environment.py:104`) calls `validate_lock` at `:115` on committed
  bytes. It is called by `prepare_frozen_artifact` at `artifact_preparation.py:144` and again by the
  recheck at `planner_environment.py:169`.
- `provision_environment` (`planner_environment.py:148`) rebuilds the key immediately before uv
  (`:169`), refuses drift (`:172`), and only after a non-zero `uv sync` (`:194`) builds owners
  (`:195`) and classifies (`:196`). A recognized outage raises `EnvironmentUnavailable` (`:197`);
  anything else raises `EnvironmentIncompatible` (`:198`).
- `prepare_frozen_artifact` is its only production caller, at `artifact_preparation.py:158`.
  `:146-149` and `:160-163` translate to `FrozenEnvironmentUnavailable` and
  `FrozenEnvironmentIncompatible`.

### Paths that reach it

| Entry point | Call chain |
|---|---|
| `algua deployment prepare NAME` | mounted at `algua/cli/main.py:58`; `deployment_cmd.py:66` `prepare` → `:72` `prepare_frozen_artifact` → environment seam |
| `algua paper intake` | `paper_cmd.py:307` `intake` → `:344` `run_intake` → `intake.py:224` default step `prepare_and_verify_frozen` → `:263` → `:96` `prepare_frozen_artifact` |
| `algua paper merge-back` | `paper_cmd.py:402` → `:565` local `intake()` → `:569` `run_intake`; invoked by `operator/mergeback.py:354` `_do_intake` at `:361`, after a passing promote |
| Merge-back drainer | `deploy/systemd/algua-mergeback-drain.service:22` → drain script → `algua operator lock-run -- algua paper merge-back ...` (per `paper_cmd.py:450-451`), then the row above |

`run_intake(prepare_and_verify=...)` is an injection seam used by tests. Production callers at
`paper_cmd.py:344` and `:569` pass none. A refusal reaches `intake.py:268`, and only
`frozen_environment_unavailable` stops admission and queues the rest (`:273`). The CLI retry
allowlist is at `algua/cli/errors.py:150`.

### Paths that do not reach it

- `algua deployment verify` (`deployment_cmd.py:79`) → `verify_frozen_artifact`
  (`artifact_verification.py:26`) → `verify_bundle` and `verify_published_environment`
  (`environment_store.py:92`) → `verify_environment`. It reads the ledger and store only. It acquires
  nothing and never reads or normalizes a lock.
- `frozen_runtime.py:80` uses the same `verify_published_environment`.
- `environment_store.py:23` imports `algua.registry.planner_environment`, so these processes *load*
  the lock module, but no function of it is called on these paths.

The merge-back quality gate reaches this code only as test execution; see the readiness report's
interpreter-selection finding.

## 9. Identity and compatibility impact

| Item | Effect |
|---|---|
| `uv.lock`, `pyproject.toml`, `.python-version` | unchanged |
| Installer argv, `CREATE_FLAGS`, `SYNC_FLAGS`, uv input | unchanged; uv still receives the exact locked URL |
| `build_inputs_digest`, `dependency_hash`, `environment_key`, inventory and environment digests | no input changes for a given interpreter. `validate_lock` returns None and `EnvironmentKey` has no wheel field (`environment_contract.py:75`). The key already separates interpreters by full version through `current_interpreter_identity` (`planner_environment.py:84`) |
| Descriptor, digest and schema versions; publication and verifier policy; signers | unchanged |
| Recorded descriptors and published objects | unchanged; verification never recomputes them from the checkout |
| Existing `uv.lock` wheels | at baseline, all 1,900 raw keys are their own identity on both interpreters (*probed*). The lock has no IP-literal or numeric host |
| Persisted wheel identity | none found: in `algua/`, "wheel" appears only in the lock, outage, environment and errors modules, and the identity is held only in the local set and the in-memory owners map |

Source-level hash impact is real and must not be denied. `planner_environment_lock.py` is under
`algua/`, so any edit to it changes the exported source bundle. A later `deployment prepare` at the
new commit gets a new `bundle_digest` and `manifest_digest`. `code_hash` covers a strategy's
first-party import closure; no module under `strategies`, `features`, `portfolio`, `contracts` or
`primitives` imports `algua.registry` directly, which suggests this module is outside those closures
but does not prove it. The implementation must report the actual before and after `code_hash` for
every bundled strategy. If any changes, stop and flag it.

This section covers repository source only. It makes no claim about any production registry's
contents.
