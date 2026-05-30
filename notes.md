# Steering Rack Calibration & Patcher Notes

![HCA5 goes to 11](HCA5.gif)

These are some of my notes/observations of how this thing behaves..  

---

## Test Process & Vehicle

Im testing on my 8J TT, with 3001 8J rack firmware.  TTs are special and have their own ever so slightly different firmware. Golf 3001 vs TT 3001 is 97 bytes different or something out of the 344kb application section. No fucking clue what audi changed, but i have some suspicions. too lazy to type all that up... has several probably bitmasks set differently ,and at least one block with some sort of curve/dataset presumably.  PLA doesnt seem to work, iv tried. Adaptation channel saves/accepts, and it faults, but the measuring block for on/off is blank, while DSR/HCA it works. Rack just status 2s PLA message. HCA works fine. DSR untested. HCA works. TT SSP claims TT firmware exists to remove DSR.

Dataset 237 is the TTS, Dataset 311 is the passat nms.

* **Tires**: 255/35/19 tires. is TT so TT suspension difs and TT steering ratio, higher than golfs. 
* **Test Process**: park in my driveway, which was wet because it rained, center wheel, and run a script to send x HCA command at status 7 for 5s, and log the angle/angular velocity for that, and then plot it all. The graphs are technically time aligned from when the LH2_something message goes from 1 to 8 indicating the rack has entered HCA. not that it matters much, its a neglible amount of time.
* **Dataset Flashing**: after flashing datasets the rack goes orange eps light, and wants you to drive... so my tires were wet and it was not in the same spot.. i logged 237 data, switched to 311, drove, parked, logged 311, switched to 237, drove, parked, logged, switched back to 311, drove, parked, logged 311 again.  so hopefully the tires were similarly wet etc etc.... not very scientific, but whatever... dont have perfect steering rack loading machine so dry steering will have to do. 

---

## Key Memory Address Map (Version 3001)

| Parameter / Limit | Offset Address | Default Hex Value | Patched Hex Value | Description & Purpose |
|:---|:---:|:---:|:---:|:---|
| **Disengage Countdown** | `0x0005D249` | `\x64`| `\x00` | Timebomb patch |
| **Minimum Activation Speed** | `0x0005D2AE` | `\x14` (20 km/h) | `\x00` | Min Speed patch |
| **Command Reject Limit** | `0x0005D0A8` | `\xcc\x00` (204 somethings) | `\x54\x01` (340 somethings) | Reject limit. above this rack status 4's |
| **Command Truncate Limit** | `0x0005D0A6` | `\xcc\x00` (204 somethings) | `\x54\x01` (340 somethings) | Truncate limit. Above this rack truncates and doesnt well, do any more. does not reject or fault. |

A6 and A8 are in some internal units. HCA command (ie, 300) * 0.662ish = internal units for this check.... 300 according to clanker comes out at 199.4 or something against this check. which would make 307 the reject, yet its not.. seems like somehow the ones place is ignored.. bitmask would make sense but then 340 would be 336 with same bitmask, and would reject at like 505, and it doesnt, it rejects at 510ish, where id expect 340 to reject. so no idea. 

* **204** = 300 command limit
* **340** = ~511 command (+- a few, honestly dont remember what it rejected at).  
* **804** = rack eps faults before this/otherwise doesnt make it angry.  

---

## EPS Faults

At 0 speed, the rack happily accepts up to 632 command, and hard eps faults at 633 and above. like, no assist angry chimes red eps light. ignition cycle clears. I suspect its failing some torque check. seems to be after a torque ramp (it def isnt applying command torque instantly) as even 0-633 starts moving a little before it faults.. ramp is weird, seems fast, but not at the same time. also seems to be before HCA5 centering force is accounted for (as centering force would reduce final torque), since HCA5 faults at the same amount. 

500 command works up to at least 19kmh without fault. 490ish works up to 27ishkmh... 500 faults around 27kmhish and above. 

iv faulted this thing like 6 times so far playing with it in neighborhood.. but its hard to narrow down conditions and also fuckass going and driving and playing wait for the EPS fault.  

---

## My Other Thoughts on Results

AIs analysis is finetm, but few interesting things to me.

### Breakaway Torque
Breakaway torque is the command needed for the rack to continously spin, rather than stopping at an angle... its the torque to exceed jacking force/other angle coupled characteristics, and that there is always remaining torque going toward fighting friction and continuing to move, rather than stopping and using all the torque to hold position. 

* **On 237**: 500 is borderline... angle results vary a lot, it wants to keep moving... often it nearly stops but keeps slowly creeping... if like, command 500 for 1s, then letoff briefly, then command again, its able to "hammer" its way and keep moving, which is interesting..  even a very slight nudge from driver seems to help HCA a *lot*, and i think it sees the mass of the wheel as a brief nudge forward, and thats why this works.
* **On 311**: breakaway is 500. 

### Max Angle / Endstop Behavior
In all tests (above break loose torque, see above), 237 hit a soft stop at ~450* and stopped cleanly. 311 on the other hand, hit the same soft stop at 500 command, but at 600 and 632 it managed to pass it and crash into the endstop at ~520*.. you can even see its angular velocity go negative in the time vs angular graphs at 600 and 632 from it bouncing off.  Passat obviously has more torque/capability at the same HCA command, but at 600/632, i suspect some other torque limit is being reached and other characteristics are at play... both 237 and 311 over 700*/s, and arent thaaaat far apart, 311 crashes into the stop. wonder if the TT has some angle related characteristics, or something else (like some sort of dampening or more complicated characteristic) causing this differing behavior. 

### Driver Torque Sensor
I decided to measure the driver torque sensor as well, because as mentioned in breakaway, the mass of the wheel being accelerated/decelerated creates some torque on it. 

On 311, these numbers are massively higher than 237.. i suspect 311 is somehow accelerating/jerking much more... i suspect 237 has some sort of dampening map thats much more aggressive than 311. its not just raw torque or other "conventional" limiters alone making 311 so much better. I believe all or many of the steer characteristics affect HCA, dampening etc. 

### Stock Torque Limit Capabilities / Does HCA7 Suck?
Fucking complicated thing. iv seen lots of people suggesting HCA7 is plenty as it can easily exceed lat accel limits, aand that its a piece of shit that will never perform well even though its peak lat accel capabilities are plenty... 

even 300 on 237, which is probably on the shittier performing side of datasets can definitely exceed lat accel limits, at least at some speeds... but theres definitely astrisks.

The biggest imo, is steer rate. yes, it can reach sufficient steer angle for a pretty damn high lat accel at at least some speeds, but it cant do it fast enough to be very useful a lot of the time...  being able to reach sufficient lat accel by the time im on the wrong side of the road doesnt do me any good for making a turn now does it.

the torque controller isnt helping... the feedforward applies torque proportionally lat accel, which only handles torque needed to *hold* steer angle (ideally), and the PID handles additional torque needed to *move* the wheel... its abnormally dogshit because the feedforward expects that 0 torque will produce 0 angle (self center), and obviously HCA7 doesnt do that... otherwise, its poorly tuned and i suspect retuning the PID alone would make it much better. plus speed variable tuning, even better... or a fancier controller. been fucking with it.

Other steer characteristics seem to also affect HCA... annecdotaly, i think HCA behaves much different if you gradually ramp torque vs just, slam full torque. probably some sort of dampening... I also think it has a torque ramp internally that behaves weirdly... it may value smoother torque... im kinda wondering if it ramps down much faster than it ramps up, unintentionally reducing torque if the command is spikey (more than the command should be).
