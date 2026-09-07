"""For every Legendary Monuments pedestal, list the item ids it references.

Whether a Medallion of Renewal is worth spending comes down to one thing: can you
obtain the pedestal's key items OUTSIDE the structure? If the item only drops inside
(or only from the boss the pedestal itself summons), renewing is pointless.
"""
import zipfile, glob, re, subprocess, os

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

JAR = glob.glob(COBBLEMON_DIR + '/mods/legendarymonuments-*.jar')[0]
z = zipfile.ZipFile(JAR)

peds = [n for n in z.namelist()
        if '/pedestals/entity/' in n and n.endswith('BlockEntity.class') and '$' not in n]

ID = re.compile(r"'([a-z_]+:[a-z_0-9/]+)'")
CFG = re.compile(r"'([A-Z][A-Z_]*PEDESTAL[A-Z_]*)'")
REWARD = re.compile(r"'(You received [^']*)'")

print('%-14s %-8s %s' % ('PEDESTAL', 'REWARD?', 'ITEM IDS REFERENCED'))
print('-' * 100)
for p in sorted(peds):
    nm = p.split('/')[-1].replace('PedestalBlockEntity.class', '')
    if nm in ('Base', 'Dual', ''):
        continue
    out = subprocess.run(['python3', '/tmp/cpstr.py', JAR, p],
                         capture_output=True, text=True).stdout
    ids = sorted({i for i in ID.findall(out)
                  if not i.split(':')[0] in ('net', 'java', 'javax')})
    rew = REWARD.findall(out)
    has_reward = 'YES' if 'giveReward' in out else '-'
    print('%-14s %-8s %s' % (nm, has_reward, ', '.join(ids) if ids else '(none literal)'))
    if rew:
        print('%-14s %-8s   reward msg: %s' % ('', '', ' | '.join(rew)))

print()
print('=== PedestalConfig defaults ===')
out = subprocess.run(['python3', '/tmp/cpstr.py', JAR,
                      'com/jorgaomc/legendarymonuments/config/PedestalConfig.class'],
                     capture_output=True, text=True).stdout
keys = sorted(set(CFG.findall(out)))
ids = sorted({i for i in ID.findall(out) if i.split(':')[0] not in ('net', 'java')})
print('config keys: %d' % len(keys))
for k in keys:
    print('   %s' % k)
print()
print('item ids in config: %s' % ', '.join(ids))
