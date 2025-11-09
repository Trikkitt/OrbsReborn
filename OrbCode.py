import network
import espnow
import OrbFunctions
import uos
import time
from machine import deepsleep,UART,reset

#uos.dupterm(None,1)
uart = UART(0,115200,bits=8, parity=None, stop=1, timeout=2, timeout_char=2, rxbuf=255)


CodeVersionHigh=1
CodeVersionLow=0
PICVersionHigh=0
PICVersionLow=0
VersionChange=True

sta = network.WLAN(network.WLAN.IF_STA)
sta.active(True)
sta.disconnect() 
sta.config(channel=1)
e = espnow.ESPNow()
e.active(True)


gamehost=OrbFunctions.DiscoverHost(e,sta,uart)
AliveInterval=30
LastAliveMsg=time.time()

while True:
    if VersionChange==True:
        VersionChange=False
        msg=bytearray(b'\xfe\x07')
        msg.append(CodeVersionHigh)
        msg.append(CodeVersionLow)
        msg.append(OrbFunctions.GetVersionHigh())
        msg.append(OrbFunctions.GetVersionLow())
        msg.append(PICVersionHigh)
        msg.append(PICVersionLow)
        crc=OrbFunctions.crc16(msg)
        msg.append(crc & 255)
        msg.append(crc >> 8)
        e.send(gamehost,msg)
        
    if time.time()>LastAliveMsg:
        LastAliveMsg=time.time() + AliveInterval
        awakemsg=bytearray(b'\xfe\x06')
        awakemsg.extend(sta.config('mac'))
        crc=OrbFunctions.crc16(awakemsg)
        awakemsg.append(crc & 255)
        awakemsg.append(crc >> 8)
        e.send(gamehost,awakemsg)
        
    if (uart.any()):
        cmd=uart.read(10)
        e.send(gamehost,cmd)
        #if OrbFunctions.crc16(cmd)==0:
        if cmd[0]<101: # Message for server
            e.send(gamehost,cmd)
        else:
            Acknowledge=False
            if cmd[0]==0xCD:
                PICVersionHigh=cmd[1]
                PICVersionLow=cmd[2]
                VersionChange=True
                Acknowledge=True
            if Acknowledge==True:
                reply=bytearray(b'\xff\x00\x00\x00\x00\x00\x00')
                reply.extend(cmd[0])
                crc=OrbFunctions.crc16(reply)
                reply.append(crc >> 8)
                reply.append(crc & 255)
                uart.write(reply)
                
    if (e.any()):
        host,msg=e.irecv()
        if len(msg)>1:
            #print("received msg")
            if OrbFunctions.crc16(msg)==0:
                if msg[0]<101:
                    #print(msg)
                    uart.write(msg)
                else:
                    #print("Received msg type: " + str(msg[0]))
                    if msg[0]==0xFA:
                        FailureReason=0
                        #print("Connecting wifi...")
                        if OrbFunctions.connectwifi()==True:
                            #print("Connected.")
                            if msg[1]==101:
                                filename='OrbCodeReborn.hex'
                            if msg[1]==1:
                                filename='OrbCode.py'
                            if msg[1]==2:
                                filename='OrbFunctions.py'
                            #print("Downloading file " + filename)
                            if OrbFunctions.downloadfile(filename)==True:
                                #print("Downloaded.")
                                import os
                                newfilename="new-" + filename
                                oldfilename="old-" + filename
                                filestat=os.stat(newfilename)
                                targetsize=(msg[4]*65536) + (msg[3] * 256) + msg[2]
                                
                                if filestat[6]==targetsize:
                                    try:
                                        os.remove(oldfilename)
                                    except:
                                        a=2
                                    try:
                                        os.rename(filename,oldfilename)
                                        os.rename(newfilename,filename)
                                        reply=bytearray(b'\xfa')
                                        reply.append(msg[1])
                                        reply.extend(b'\x00\x00\x00\x00\x00\x00')
                                        crc=OrbFunctions.crc16(reply)
                                        reply.append(crc >> 8)
                                        reply.append(crc & 255)
                                        e.send(gamehost,reply)
                                        uart.write(reply)
                                    except:
                                        FailureReason=4
                                    
                                else:
                                    #print("file size mismatch")
                                    FailureReason=3
                            else:
                                FailureReason=2
                        else:
                            FailureReason=1
                        #print("Result code: " + str(FailureReason))
                        if FailureReason>0: 
                            sta.disconnect()
                            sta.config(channel=1)
                            reply=bytearray(b'\xfe\x08')
                            reply.append(FailureReason)
                            reply.extend('\x00\x00\x00\x00\x00')
                            crc=OrbFunctions.crc16(reply)
                            reply.append(crc & 255)
                            reply.append(crc >> 8)
                            e.send(gamehost,reply)
                            
                            
                    if msg[0]==1:
                        reply=bytearray(b'\xff\x02\x00\x00\x00\x00\x00\x00')
                        crc=OrbFunctions.crc16(reply)
                        reply.append(crc & 255)
                        reply.append(crc >> 8)
                        e.send(gamehost,reply)

                

