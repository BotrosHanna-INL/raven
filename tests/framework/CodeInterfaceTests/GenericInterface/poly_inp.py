import numpy as np
import os

def eval(x,y,z):
  dat=[]
  c = 0
  for i in [0.3,0.5,0.7,1.0]:
    for j in [1.3,1.5,1.7,2.0]:
      c+=1
      dat.append([c,i,j,x,y,z,(i-x)*(j-y)+z])
  return dat

def run(xin,yin,out):
  inx = file(xin,'r')
  iny = file(yin,'r')
  if not os.path.isfile('dummy.e'):
    raise IOError('Missing dummy exodus file "dummy.e"!')
  for line in inx:
    if line.startswith('x ='):
      x=float(line.split('=')[1])
    elif line.startswith('z ='):
      z=float(line.split('=')[1])
  for line in iny:
    if line.startswith('y ='):
      y=float(line.split('=')[1])

  dat = eval(x,y,z)

  outf = file(out+'.csv','w')
  outf.writelines('step,i,j,x,y,z,poly\n')
  for e in dat:
    outf.writelines(','.join(str(i) for i in e)+'\n')
  outf.close()

if __name__=='__main__':
  import sys
  args = sys.argv
  inp1 = args[args.index('-i')+1] if '-i' in args else None
  inp2 = args[args.index('-a')+1] if '-a' in args else None
  out  = args[args.index('-o')+1] if '-o' in args else None
  run(inp1,inp2,out)
