import sys, zipfile, struct, re
def strings(data):
    # parse java class constant pool for CONSTANT_Utf8
    out=[]
    if data[:4]!=b'\xca\xfe\xba\xbe': return out
    cnt=struct.unpack('>H',data[8:10])[0]
    i=10; n=1
    while n<cnt:
        tag=data[i]; i+=1
        if tag==1:
            l=struct.unpack('>H',data[i:i+2])[0]; i+=2
            out.append(data[i:i+l].decode('utf8','replace')); i+=l
        elif tag in (7,8,16,19,20): i+=2
        elif tag==15: i+=3
        elif tag in (3,4,9,10,11,12,17,18): i+=4
        elif tag in (5,6): i+=8; n+=1
        else: raise ValueError('tag %d at %d'%(tag,i))
        n+=1
    return out
z=zipfile.ZipFile(sys.argv[1])
pat=sys.argv[3] if len(sys.argv)>3 else None
for entry in sys.argv[2].split(','):
    print('#####', entry)
    for s in strings(z.read(entry)):
        if pat and not re.search(pat,s,re.I): continue
        print(repr(s))
