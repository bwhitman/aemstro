import sys
import os
import re
import struct

#TODO : add parsing checks, handle errors more gracefully

def toFloat24(f):
	f=bytearray(struct.pack('f', f))
	s=f[3]>>7
	tmp=(((f[3]<<1)|(f[2]>>7))&0xFF)-0x40
	tmp2=(((f[0])|(f[1]<<8)|(f[2]<<16))>>7)&0xFFFF
	if tmp>=0:
		tmp2|=tmp<<16
		tmp2|=s<<23
	else:
		tmp2=s<<23
	return tmp2

class DVLE(object):
	def __init__(self, type):
		self._main = 0
		self._endmain = 0
		self._type = type
		self._const = []
		self._label = []
		self._labelmap = {}
		self._outmap = []
		self._inmap = []
		self._symbol = bytearray()
		self._symbolnum = 0

	def setMain(self, main):
		self._main = main

	def setEndmain(self, endmain):
		self._endmain = endmain

	#binary word tuple
	def addConstant(self, const):
		self._const.append(const)

	#(reg, x, y, z, w)
	def addConstantF(self, const):
		self._const.append((const[0]<<16, toFloat24(const[1]), toFloat24(const[2]), toFloat24(const[3]), toFloat24(const[4])))

	#string
	def addSymbol(self, s):
		ret=len(self._symbol)
		self._symbol+=bytearray(s, "ascii")+bytearray(b"\x00")
		self._symbolnum+=1
		return ret

	#(code offset, symbol offset)
	def addLabel(self, label):
		if label[1]=="main":
			self.setMain(label[0])
		elif label[1]=="endmain":
			self.setEndmain(label[0])
		self._label.append((label[0],self.addSymbol(label[1])))
		self._labelmap[label[1]]=label[0]

	def getLabelAddress(self, label):
		if label in self._labelmap:
			return self._labelmap[label]
		else:
			return 0x0

	#binary word tuple
	def addOutput(self, out):
		self._outmap.append(out)

	#(startreg, endreg, symbol offset)
	def addInput(self, ind):
		self._inmap.append((ind[0],ind[1],self.addSymbol(ind[2])))

	def toBinary(self):
		ret=[]

		offsetConst=0x40
		offsetLabel=offsetConst+len(self._const)*0x14
		offsetOutmap=offsetLabel+len(self._label)*0x10
		offsetInmap=offsetOutmap+len(self._outmap)*0x8
		offsetSymbol=offsetInmap+len(self._inmap)*0x8

		ret.append(0x454C5644) #DVLE magic
		ret.append((self._type&1)<<16)
		ret.append(self._main)
		ret.append(self._endmain)
		ret.append(0x00000000) # ?
		ret.append(0x00000000) # ?
		ret.append(offsetConst)
		ret.append(len(self._const))
		ret.append(offsetLabel)
		ret.append(len(self._label))
		ret.append(offsetOutmap)
		ret.append(len(self._outmap))
		ret.append(offsetInmap)
		ret.append(len(self._inmap))
		ret.append(offsetSymbol)
		ret.append(len(self._symbol))

		for k in self._const:
			ret.append(k[0])
			ret.append(k[1])
			ret.append(k[2])
			ret.append(k[3])
			ret.append(k[4])

		i=0
		for k in self._label:
			ret.append(i)
			ret.append(k[0])
			ret.append(0x00000000) # ?
			ret.append(k[1])
			i+=1

		for k in self._outmap:
			ret.append(k[0])
			ret.append(k[1])

		for k in self._inmap:
			ret.append(k[2])
			ret.append(((k[1]&0xFFFF)<<16)|(k[0]&0xFFFF))

		retb=bytearray()
		for k in ret:
			retb+=struct.pack("I",k)
		retb+=self._symbol

		return retb


class DVLP(object):
	def __init__(self):
		self._code = []
		self._opdesc = []

	def clearCode(self):
		self._code[:] = []

	def addInstruction(self, inst):
		self._code.append(inst)
		return len(self._code)

	def addOpdesc(self, opdesc):
		self._opdesc.append(opdesc)
		return len(self._opdesc)

	def getCodelength(self):
		return len(self._code)

	def toBinary(self):
		ret=[]

		offsetCode=0x28
		offsetOpdesc=offsetCode+len(self._code)*0x4
		symbolOffset=offsetOpdesc+len(self._opdesc)*0x8

		ret.append(0x504C5644) #DVLP magic
		ret.append(0x00000000) # ?
		ret.append(offsetCode)
		ret.append(len(self._code))
		ret.append(offsetOpdesc)
		ret.append(len(self._opdesc))
		ret.append(symbolOffset)
		ret.append(0x00000000) # ?
		ret.append(0x00000000) # ?
		ret.append(0x00000000) # ?

		retb=bytearray()
		for k in ret:
			retb+=struct.pack("I",k)
		for k in self._code:
			retb+=struct.pack("I",k)
		for k in self._opdesc:
			retb+=struct.pack("I",k[0])
			retb+=struct.pack("I",k[1])

		return retb


class DVLB(object):
	def __init__(self):
		self._dvlp = DVLP()
		self._dvle = []

	def getDVLP(self):
		return self._dvlp

	def addDVLE(self, dvle):
		self._dvle.append(dvle)

	def toBinary(self):
		ret=[]

		ret.append(0x424C5644) #DVLB magic
		ret.append(len(self._dvle))

		off=len(self._dvle)*0x4+0x8
		retb=bytearray()
		retb+=self._dvlp.toBinary()
		for k in self._dvle:
			ret.append(off+len(retb))
			retb+=k.toBinary()

		retb2=bytearray()
		for k in ret:
			retb2+=struct.pack("I",k)

		return retb2+retb


def getRegisterFromNameDst(s):
	if s[0]=="o": # output
		return int(s[1:])
	elif s[0]=="v": # attribute
		print("error : "+s+" cannot be accessed from dst")
	elif s[0]=="r": # temporary register
		return int(s[1:])+0x10
	elif s[0]=="c": # uniform
		print("error : "+s+" cannot be accessed from dst")
	elif s[0]=="d": # direct hex; unambiguous
		return int("0x"+s[1:],0)
	else:
		print("error : "+s+" is not a valid register name")

def getRegisterFromNameSrc1(s):
	if s[0]=="o": # output
		print("error : "+s+" cannot be accessed from src1")
	elif s[0]=="v": # attribute
		return int(s[1:])
	elif s[0]=="r": # temporary register
		return int(s[1:])+0x10
	elif s[0]=="c": # uniform
		return int(s[1:])+0x20
	elif s[0]=="d": # direct hex; unambiguous
		return int("0x"+s[1:],0)
	else:
		print("error : "+s+" is not a valid register name")

def getRegisterFromNameSrc2(s):
	if s[0]=="o": # output
		print("error : "+s+" cannot be accessed from src2")
	elif s[0]=="v": # attribute
		return int(s[1:])
	elif s[0]=="r": # temporary register
		return int(s[1:])+0x10
	elif s[0]=="c": # uniform
		print("error : "+s+" cannot be accessed from src2")
	elif s[0]=="d": # direct hex; unambiguous
		return int("0x"+s[1:],0)
	else:
		print("error : "+s+" is not a valid register name")

def assembleFormat1(d):
	return (d["opcode"]<<26)|((d["dst"]&0x1F)<<21)|((d["src1"]&0x7F)<<12)|((d["src2"]&0x1F)<<7)|(d["extid"]&0x7F)

def parseFormat1(dvle, s):
	operandFmt="[^\s,]*"
	descFmt="(?:(?:0x)[0-9a-f]+)|[0-9a-f]+"
	p=re.compile("^\s*("+operandFmt+"),\s*("+operandFmt+"),\s*("+operandFmt+")\s*\(("+descFmt+")\)")
	r=p.match(s)
	if r:
		return {"dst" : getRegisterFromNameDst(r.group(1)),
			"src1" : getRegisterFromNameSrc1(r.group(2)),
			"src2" : getRegisterFromNameSrc2(r.group(3)),
			"extid" : int(r.group(4),0)}
	else:
		raise Exception("encountered error while parsing instruction")

def assembleFormat2(d):
	print(d)
	return (d["opcode"]<<26)|((d["flags"]&0xF)<<22)|((d["addr"]&0xFFF)<<10)|(d["ret"]&0x3FF)

def parseFormat2(dvle, s):
	operandFmt1="[^\s,]*"
	# operandFmt2="(?:(?:0x)[0-9a-f]+)|[0-9a-f]+"
	operandFmt3="0b[0-1]+"
	# p=re.compile("^\s*("+operandFmt1+"),\s*("+operandFmt2+"),\s*("+operandFmt3+")")
	p=re.compile("^\s*("+operandFmt1+"),\s*("+operandFmt3+")")
	r=p.match(s)
	print(r.group(1))
	print(dvle.getLabelAddress(r.group(1)))
	if r:
		return {"addr" : dvle.getLabelAddress(r.group(1)),
			"ret" : 0,
			"flags" : int(r.group(2),0)}
	else:
		raise Exception("encountered error while parsing instruction")

def assembleFormat3(d):
	return (d["opcode"]<<26)

def parseFormat3(dvle, s):
	# doesn't check that there are no operands.
	# (but really if you want to be an idiot and add useless operands to your code, go ahead)
	return {}

def assembleFormat4(d):
	return (d["opcode"]<<26)|((d["dst"]&0x1F)<<21)|((d["src1"]&0x7F)<<12)|(d["extid"]&0x7F)

def parseFormat4(dvle, s):
	operandFmt="[^\s,]*"
	descFmt="(?:(?:0x)[0-9a-f]+)|[0-9a-f]+"
	p=re.compile("^\s*("+operandFmt+"),\s*("+operandFmt+")\s*\(("+descFmt+")\)")
	r=p.match(s)
	if r:
		return {"dst" : getRegisterFromNameDst(r.group(1)),
			"src1" : getRegisterFromNameSrc1(r.group(2)),
			"extid" : int(r.group(3),0)}
	else:
		raise Exception("encountered error while parsing instruction")

def assembleFormat5(d):
	return (d["opcode"]<<26)|((d["cmpx"]&0x7)<<24)|((d["cmpy"]&0x7)<<21)|((d["src1"]&0x7F)<<12)|((d["src2"]&0x1F)<<7)|(d["extid"]&0x7F)

def parseFormat5(dvle, s):
	operandFmt="[^\s,]*"
	descFmt="(?:(?:0x)[0-9a-f]+)|[0-9a-f]+"
	opFmt="[0-9]+"
	p=re.compile("^\s*("+operandFmt+"),\s*("+opFmt+"),\s*("+opFmt+"),\s*("+operandFmt+")\s*\(("+descFmt+")\)")
	r=p.match(s)
	if r:
		return {"src1" : getRegisterFromNameSrc1(r.group(1)),
			"cmpx" : int(r.group(2)),
			"cmpy" : int(r.group(3)),
			"src2" : getRegisterFromNameSrc2(r.group(4)),
			"extid" : int(r.group(5),0)}
	else:
		raise Exception("encountered error while parsing instruction")

def assembleFormat6(d):
	return (d["opcode"]<<26)|((d["dst"]&0x1F)<<21)|((d["src2"]&0x7F)<<7)|((d["src1"]&0x1F)<<14)|(d["extid"]&0x7F)

instList={}
fmtList=[(parseFormat1, assembleFormat1), (parseFormat2, assembleFormat2), (parseFormat3, assembleFormat3), (parseFormat4, assembleFormat4), (parseFormat5, assembleFormat5), (parseFormat1, assembleFormat6)]

instList["add"]={"opcode" : 0x00, "format" : 0}
instList["dp3"]={"opcode" : 0x01, "format" : 0}
instList["dp4"]={"opcode" : 0x02, "format" : 0}
instList["dph"]={"opcode" : 0x03, "format" : 0}
instList["op4"]={"opcode" : 0x04, "format" : 3}
instList["ex2"]={"opcode" : 0x05, "format" : 3}
instList["lg2"]={"opcode" : 0x06, "format" : 3}
instList["op7"]={"opcode" : 0x07, "format" : 3}
instList["mul"]={"opcode" : 0x08, "format" : 0}
instList["sge"]={"opcode" : 0x09, "format" : 0}
instList["slt"]={"opcode" : 0x0a, "format" : 0}
instList["flr"]={"opcode" : 0x0B, "format" : 3}
instList["max"]={"opcode" : 0x0C, "format" : 0}
instList["min"]={"opcode" : 0x0D, "format" : 0}
instList["mov"]={"opcode" : 0x13, "format" : 3}
instList["dphi"]={"opcode" : 0x18, "format" : 5}
instList["sgei"]={"opcode" : 0x1a, "format" : 5}
instList["slti"]={"opcode" : 0x1b, "format" : 5}
instList["if"] ={"opcode" : 0x28, "format" : 1}
instList["cmp"]={"opcode" : 0x2e, "format" : 4}
instList["end"]={"opcode" : 0x21, "format" : 2}
instList["flush"]={"opcode" : 0x22, "format" : 2}

def parseConst(dvlp, dvle, s):
	s=s.split(",")
	dvle.addConstantF((int(s[0],0), float(s[1]), float(s[2]), float(s[3]), float(s[4])))

outputTypes={"result.position" : 0x0,
			"result.color" : 0x2,
			"result.texcoord0" : 0x3,
			"result.texcoord1" : 0x5,
			"result.texcoord2" : 0x6,
			"result.view" : 0x8}

def parseOut(dvlp, dvle, s):
	s=s.split(",")
	s[0]=s[0].replace(" ", "")
	s[1]=s[1].replace(" ", "")
	reg=int(s[0][1:])
	if s[1] in outputTypes:
		type=outputTypes[s[1]]
		dvle.addOutput((type|(reg<<16), 0x00000000))

swizVal={"w":0x3,"z":0x2,"y":0x1,"x":0x0}

def parseOpdesc(dvlp, dvle, s):
	s=s.split(",")
	for k in range(len(s)):
		s[k]=s[k].replace(" ", "")
	#dst mask
	mask=0
	for k in range(4):
		if s[0][k]!="_":
			mask|=1<<(3-k)
	swiz=[0,0]
	for i in range(2):
		l=s[1+i]
		for k in range(4):
			swiz[i]=((swiz[i]<<2)|swizVal[l[k]])
	dvlp.addOpdesc(((1<<31)|(swiz[1]<<14)|(swiz[0]<<5)|(mask),0x0000000F))

def parseUniform(dvlp, dvle, s):
	s=s.split(",")
	for k in range(len(s)):
		s[k]=s[k].replace(" ", "")
	dvle.addInput((int(s[0],0),int(s[1],0),s[2]))

dirList={}

dirList["const"]=(parseConst)
dirList["out"]=(parseOut)
dirList["opdesc"]=(parseOpdesc)
dirList["uniform"]=(parseUniform)

def parseInstruction(dvle, s):
	s=s.lower()
	p=re.compile("^\s*([^\s]*)(.*)")
	r=p.match(s)
	if r:
		name=r.group(1)
		if name in instList:
			fmt=instList[name]["format"]
			out=fmtList[fmt][0](dvle, r.group(2))
			out["opcode"]=instList[name]["opcode"]
			v=fmtList[fmt][1](out)
			return v
		else:
			print(name+" : no such instruction")
	return None

def parseLabel(s):
	s=s.lower()
	p=re.compile("^\s*([a-z_0-9]*):")
	r=p.match(s)
	if r:
		return r.group(1)
	return None

def parseLine(dvlp, dvle, l, mode):
	l=l.split(";")[0] #remove comments

	k=0
	while (k<len(l) and (l[k]==" " or l[k]=="	")):
		k+=1
	l=l[k:]

	if len(l)>1:
		if l[0]==".": #directive
			if not(mode):
				p=re.compile("^\s*\.([^\s]*)(.*)")
				r=p.match(l)
				if r:
					name=r.group(1)
					if name in dirList:
						dirList[name](dvlp, dvle, r.group(2))
					else:
						print(name+" : no such directive")
		else:
			v=parseLabel(l)
			if v: #label
				if not(mode):
					dvle.addLabel((dvlp.getCodelength(), v))
			else: #instruction
				v=parseInstruction(dvle, l)
				if v:
					dvlp.addInstruction(v)

if len(sys.argv)<3:
	print("AEMSTRO AS :")
	print("    aemstro_as.py  <input.vsh>  <output.shbin>")
else:
	dvlb=DVLB()
	dvle=DVLE(0x0)

	with open(sys.argv[1], "r") as f:
		for line in f:
			parseLine(dvlb.getDVLP(), dvle, line, False)
	dvlb.getDVLP().clearCode()
	with open(sys.argv[1], "r") as f:
		for line in f:
			parseLine(dvlb.getDVLP(), dvle, line, True)

	dvlb.addDVLE(dvle)

	open(sys.argv[2],"wb").write(dvlb.toBinary())
