import network
import espnow
import time
import random
import AudioPlayer
import binascii
import neopixel
import OrbFunctions
from sendir import SendIR

from machine import I2S
from machine import SDCard
from machine import Pin

LaserVersionLow=1
LaserVersionHigh=1

def get_config():
    import json
    try:
        configfile=open("config.txt","r")
        cfgdict=json.load(configfile)
        configfile.close()
    except BaseException as e:
        cfgdict={}
    return cfgdict


def save_config(cfgdict):
    import json
    savesuccess=False
    try:
        cfgtxt=json.dumps(cfgdict)
        configfile=open("config.txt","w")
        configfile.write(cfgtxt)
        configfile.close()
        savesuccess=True
    except:
        savesuccess=False

def crc16(data):
    crc = 0xFFFF 
    for byte in data:
        crc = crc ^ byte
        for _ in range(8):
            if (crc & 0x01)==0:
                crc=crc >> 1
            else:
                crc=crc >> 1
                crc = crc ^ 0xA001
            crc &= 0xFFFF
    return crc


def LaserDiscoverHost(pe,psta):
    bcast = b'\xff' * 6
    mygamehost=b'\xff' * 6
    discoveryPacket=bytearray(b'\xC1\x05')
    discoveryPacket.extend(psta.config('mac'))
    crc=crc16(discoveryPacket)
    discoveryPacket.append(crc & 255)
    discoveryPacket.append(crc >> 8)

    print("discovery in progress...")
    dcount=0
    while bcast==mygamehost:
        dcount+=1
        print(dcount)
        pe.send(bcast,discoveryPacket)
        host, msg=pe.irecv(2000)
        if host:
            if len(msg)==10:
                crc=crc16(msg)
                if crc==0 and msg[0]==0xC2 and msg[1]==0x05:
                    mygamehost=msg[2:8]
    return mygamehost


ChannelNumber=1
sta = network.WLAN(network.WLAN.IF_STA)
sta.active(True)
sta.disconnect() 
sta.config(channel=ChannelNumber)
e = espnow.ESPNow()
e.active(True)
#sta.config(pm=0) # Power management needs to be disabled if possible
sta.config(pm=sta.PM_NONE)
bcast = b'\xff' * 6
e.add_peer(bcast, channel=ChannelNumber)

trigger=Pin(40,Pin.IN, Pin.PULL_UP)
laserpin=Pin(35,Pin.OUT)
laserpin.value(0)
triggerlatch=0

shotSound=1
shotRate=10  # Shots per second up to 15.  Higher means other rates.
gameMode=0
gunID=1
ActiveInGame=0
PlaySound=0

myconfig=get_config()
if not ("gamehost" in myconfig):
    gamehost=LaserDiscoverHost(e,sta)
    myconfig["gamehost"]=gamehost
    save_config(myconfig)
else:
    gamehost=myconfig["gamehost"]

e.add_peer(gamehost)


audEnteredGame="enteredgame.raw"
audLaserShot="Laser1.raw"
audCountDown="countdown.raw"
audGoGoGo="gogogo.raw"
audGameOver="gameover.raw"
audHitConfirmed="hitconfirmed.raw"
audVictory="victory.raw"
audDefeat="defeat.raw"
audNewHighScore="newhigh.raw"
audIdle="idle.raw"
audBadHit="wrongorb.raw"

AliveInterval=30
LastAliveMsg=time.time()
LastMsg=time.time()
RegisteredOrbs=[]
AudioPlayer.LoadFile(audLaserShot)
LastShot=time.ticks_ms()
LaserOnTime=time.ticks_ms()
LaserOnPeriod=150
LaserOn=True
ir=SendIR(21)
LastUpdateSent=time.ticks_ms()
UpdatesSkipped=0
SendUpdate=False
ShotCount=0
ShotDiff=0

# 1, 2
shotTimings=[1000,1000,500,333,250,200,166,142,125,111,100,90,83,76,71,66,62]
irShot=[b"\x55\x11\xEE",b"\x55\x8A\x75",b"\x55\xB3\x4C"]

AnimationFrame=0
AnimationValue=0
LastFrame=time.ticks_ms()
LEDPin=Pin(2,Pin.OUT)
LEDStrip=neopixel.NeoPixel(LEDPin,16)
for i in range(16):
    LEDStrip[i]=(0,0,0)
while True:
    if time.ticks_diff(time.ticks_ms(),LastFrame)>30:
        LastFrame=time.ticks_ms()
        AnimationFrame+=1
        if (gameMode==1 and ActiveInGame==0) or (gameMode==6): # idle
            if AnimationFrame<30:
                AnimationValue+=2
            else:
                AnimationValue-=2
                if AnimationFrame>59:
                    AnimationValue=0
                    AnimationFrame=0
            if AnimationValue<0:
                AnimationValue=0
            if AnimationValue>255:
                AnimationValue=255
            for i in range(16):
                if gunID==0:
                    LEDStrip[i]=(AnimationValue,0,0)
                if gunID==1:
                    LEDStrip[i]=(0,AnimationValue,0)
                if gunID==2:
                    LEDStrip[i]=(0,0,AnimationValue)
        if (gameMode==1 and ActiveInGame==1) or gameMode==4: # Clicked into the game or game is running
            if AnimationFrame>6:
                AnimationFame=0
                AnimationValue+=1
                if AnimationValue>=16:
                    AnimationValue=0
                for i in range(16):
                    if i==AnimationValue:
                        if gunID==0:
                            LEDStrip[i]=(150,0,0)
                        if gunID==1:
                            LEDStrip[i]=(0,150,0)
                        if gunID==2:
                            LEDStrip[i]=(0,0,150)
                    else:
                        LEDStrip[i]=(0,0,0)
        if gameMode==2: # not in this game, lights out
            for i in range(16):
                LEDStrip[i]=(0,0,0)
        if gameMode==3:
            if AnimationFrame>1:
                AnimationFrame=0
                AnimationValue=random.randint(0,16)
                for i in range(16):
                    if i==AnimationValue:
                        LEDStrip[i]=(random.randint(0,254),random.randint(0,254),random.randint(0,254))
                    else:
                        LEDStrip[i]=(0,0,0)
        LEDStrip.write()
                
    if trigger.value()!=triggerlatch:
        # trigger state changed
        print("trigger changed")
        triggerlatch=trigger.value()
        if triggerlatch==0:
            # Trigger pulled
            print("trigger pulled")
            print(time.ticks_diff(time.ticks_ms(),LastShot))
            print(shotTimings[shotRate])
            if gameMode==1 and ActiveInGame==0:
                ActiveInGame=1
                AnimationValue=0
                AnimationFrame=0
                AudioPlayer.PlayFile(audEnteredGame)
                outmsg=bytearray(b'\xCB')
                outmsg.append(1)
                while len(outmsg)<8:
                    outmsg.append(0)
                crc=crc16(outmsg)
                outmsg.append(crc & 255)
                outmsg.append(crc >> 8)
                retrycount=0
                msgsent=False
                while retrycount<6 and msgsent==False:
                    try:
                        e.send(gamehost,outmsg)
                        msgsent=True
                    except:
                        retrycount+=1
                
            if gameMode==4 and time.ticks_diff(time.ticks_ms(),LastShot)>=shotTimings[shotRate]: # can only fire when in an active game
                AudioPlayer.PlayLoadedFile() #("Laser1.raw")
                PlaySound=0
                LastShot=time.ticks_ms()
                ir.send(irShot[gunID],wait=False)
                laserpin.value(1)
                LaserOnTime=time.ticks_ms()
                LaserOn=True
                ShotCount+=1
    if LaserOn:
        if time.ticks_diff(time.ticks_ms(),LaserOnTime)>=LaserOnPeriod:
            laserpin.value(0)
            LaserOn=False
    if time.time()>LastAliveMsg: # Send alive message to game host
        LastAliveMsg=time.time() + AliveInterval
        awakemsg=bytearray(b'\xC1\x06')
        awakemsg.extend(sta.config('mac'))
        awakemsg.append(LaserVersionHigh)
        awakemsg.append(LaserVersionLow)
        crc=crc16(awakemsg)
        awakemsg.append(crc & 255)
        awakemsg.append(crc >> 8)
        retrycount=0
        msgsent=False
        while retrycount<6 and msgsent==False:
            try:
                e.send(gamehost,awakemsg)
                msgsent=True
            except:
                retrycount+=1
    if time.time()>LastMsg: # Game host has gone silent
        e.del_peer(gamehost)
        gamehost=LaserDiscoverHost(e,sta)
        e.add_peer(gamehost)
        myconfig["gamehost"]=gamehost
        save_config(myconfig)
    if PlaySound>0:
        if AudioPlayer.state==AudioPlayer.STOP:
            if PlaySound==1: # hit confirmed
                AudioPlayer.PlayFile(audHitConfirmed)
            if PlaySound==2: # Victory
                AudioPlayer.PlayFile(audVictory)
            if PlaySound==3: # Defeat
                AudioPlayer.PlayFile(audDefeat)
            if PlaySound==4: # High score
                AudioPlayer.PlayFile(audNewHighScore)
            if PlaySound==6: # bad hit
                AudioPlayer.PlayFile(audBadHit)
            PlaySound=0
    if gameMode>=3:
        if time.ticks_diff(time.ticks_ms(),LastUpdateSent)>0:
            LastUpdateSent=time.ticks_add(time.ticks_ms(),1000)
            if ShotCount==ShotDiff:
                UpdatesSkipped+=1
                if UpdatesSkipped>5:
                    SendUpdate=True
                    UpdatesSkipped=0
            else:
                SendUpdate=True
    if SendUpdate:
        SendUpdate=False
        LastUpdateSent=time.ticks_add(time.ticks_ms(),1000)
        outmsg=bytearray(b'\xCA')
        outmsg.append(ShotCount - ShotDiff)
        ShotDiff=ShotCount
        outmsg.extend(ShotCount.to_bytes(2,'big'))
        while len(outmsg)<8:
            outmsg.append(0)
        crc=crc16(outmsg)
        outmsg.append(crc & 255)
        outmsg.append(crc >> 8)
        retrycount=0
        msgsent=False
        while retrycount<6 and msgsent==False:
            try:
                e.send(gamehost,outmsg)
                msgsent=True
            except:
                retrycount+=1
        
    if (e.any()):
        host,msg=e.irecv()
        if len(msg)>2:
            if crc16(msg)==0:
                if host==gamehost: # only process messages from the game host
                    LastMsg=time.time() + AliveInterval
                    if msg[0]==0xD1: # Orb Registration
                        Orb=bytes(msg[2:8])
                        if Orb not in RegisteredOrbs:
                            RegisteredOrbs.append(Orb)
                        
                        #orbIndex=str(msg[1])
                        #Orbs[orbIndex]=msg[2:8]
                        try:
                            e.add_peer(msg[2:8])
                            print("Peer registered")
                        except:
                            print("Peer already registered")
                    #if msg[0]==0xD2: # Orb dereg
                        #orbIndex=str(msg[1])
                        #if orbIndex in Orbs:
                        #    e.del_peer(Orbs[orbIndex])
                    if msg[0]==0xD3: # relay message to orb
                        Orb=bytes(msg[1:7])
                        print("Relay to: " + str(binascii.hexlify(Orb)))
                        #orbIndex=str(msg[1])
                        #msgsent=1
                        #if orbIndex in Orbs:
                        #    outmsg=msg[2:-2]
                        outmsg=msg[7:-2]
                        while len(outmsg)<8:
                            outmsg.append(0)
                        crc=crc16(outmsg)
                        outmsg.append(crc & 255)
                        outmsg.append(crc >> 8)
                        print("Message: " + str(binascii.hexlify(outmsg)))
                        if Orb not in RegisteredOrbs:
                            print("Not registered")
                            try:
                                RegisteredOrbs.append(Orb)
                                e.add_peer(Orb)
                            except:
                                print("Already registered orb")
                        retrycount=0
                        msgsent=False
                        while retrycount<6 and msgsent==False:
                            try:
                                e.send(Orb,outmsg)
                                msgsent=True
                            except:
                                retrycount+=1
                        
                        #outmsg=bytearray(b'\xC9\xD3')
                        #outmsg.append(msg[1])
                        #outmsg.append(2)
                        #while len(outmsg)<8:
                        #    outmsg.append(0)
                        #crc=crc16(outmsg)
                        #outmsg.append(crc & 255)
                        #outmsg.append(crc >> 8)
                        #e.send(gamehost,outmsg)                        
                    if msg[0]==0xD4: # relay to all orbs
                        outmsg=msg[2:-2]
                        crc=crc16(outmsg)
                        outmsg.append(crc & 255)
                        outmsg.append(crc >> 8)
                        msgsent=0
                        for Orb in RegisteredOrbs:
                            msgsent+=1
                            retrycount=0
                            msgsent=False
                            while retrycount<6 and msgsent==False:
                                try:
                                    e.send(Orb,outmsg)
                                    msgsent=True
                                except:
                                    retrycount+=1
                        #outmsg=bytearray(b'\xC9\xD4')
                        #outmsg.append(0)
                        #outmsg.append(msgsent)
                        #while len(outmsg)<8:
                        #    outmsg.append(0)
                        #crc=crc16(outmsg)
                        #outmsg.append(crc & 255)
                        #outmsg.append(crc >> 8)
                        #e.send(gamehost,outmsg)                        
                    if msg[0]==0xD8: # new gun config
                        print("Received gun config")
                        shotSound=msg[2]
                        shotRate=msg[3]
                        gunID=msg[5]
                        ActiveInGame=msg[6]
                        if msg[1]!=gameMode: # game mode has changed!
                            print("game mode changed from " +str(gameMode) + " to " + str(msg[1]))
                            gameMode=msg[1]
                            if gameMode==1: # entered idle
                                AudioPlayer.PlayFile(audIdle)
                                AnimationValue=0
                                AnimationFrame=0
                            #if gameMode==2: # game active, this laser isn't part of it
                            if gameMode==3: # game start countdown
                                AudioPlayer.PlayFile(audCountDown)
                                AnimationValue=0
                                AnimationFrame=0
                                ShotCount=0
                                ShotDiff=0
                            if gameMode==4: # game active, you can fire
                                AudioPlayer.PlayFile(audGoGoGo)
                                AnimationValue=0
                                AnimationFrame=0
                            #if gameMode==5: # game active, you can't fire
                            if gameMode==6: # game over
                                AnimationValue=0
                                AnimationFrame=0
                                AudioPlayer.PlayFile(audGameOver)
                                SendUpdate=True
                        #outmsg=bytearray(b'\xC9\xD8')
                        #outmsg.append(0)
                        #outmsg.append(gameMode)
                        #while len(outmsg)<8:
                        #    outmsg.append(0)
                        #crc=crc16(outmsg)
                        #outmsg.append(crc & 255)
                        #outmsg.append(crc >> 8)
                        #e.send(gamehost,outmsg)
                    if msg[0]==0xD9:
                        PlaySound=msg[1]
                    if msg[0]==0xFA:
                        FailureReason=0
                        if OrbFunctions.connectwifi()==True:
                            if msg[1]==11:
                                filename='LaserCode.py'
                            if msg[1]==12:
                                filename='AudioPlayer.py'
                            if msg[1]==13:
                                filename='sendir.py'
                            if msg[1]==2:
                                filename='OrbFunctions.py'
                            if OrbFunctions.downloadfile(filename)==True:
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
                                    FailureReason=3
                            else:
                                FailureReason=2
                        else:
                            FailureReason=1
                        if FailureReason>0: 
                            sta.disconnect()
                            sta.config(channel=11)
                            reply=bytearray(b'\xfe\x08')
                            reply.append(FailureReason)
                            reply.extend('\x00\x00\x00\x00\x00')
                            crc=OrbFunctions.crc16(reply)
                            reply.append(crc & 255)
                            reply.append(crc >> 8)
                            e.send(gamehost,reply)
                if msg[0]==1:
                    reply=bytearray(b'\xff\x02\x00\x00\x00\x00\x00\x00')
                    crc=crc16(reply)
                    reply.append(crc & 255)
                    reply.append(crc >> 8)
                    retrycount=0
                    msgsent=False
                    while retrycount<6 and msgsent==False:
                        try:
                            e.send(gamehost,reply)
                            msgsent=True
                        except:
                            retrycount+=1




