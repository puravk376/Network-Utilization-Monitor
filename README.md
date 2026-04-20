# Network Utilization Monitor — SDN Mininet Project

> **Project #19** | SDN Mininet Simulation | Orange Problem Statement  
> Course Assignment — Individual Submission

---

## Problem Statement

This project implements an **SDN-based Network Utilization Monitor** using Mininet and the Ryu OpenFlow controller. The controller measures and displays real-time bandwidth utilization across the network by periodically collecting byte counters from switches, estimating per-port bandwidth usage in kbps, and updating the display every 5 seconds.

The system demonstrates:
- Controller–switch interaction via OpenFlow 1.3
- Flow rule design using match–action tables
- Real-time network behavior observation and monitoring

---

## Network Topology

```
h1 (10.0.0.1) ──┐
                 ├── s1 ──── s2 ──┬── h3 (10.0.0.3)
h2 (10.0.0.2) ──┘                 └── h4 (10.0.0.4)
```

- 2 OVS switches (s1, s2) connected via an inter-switch link
- 4 hosts with static IPs and MACs
- All links at 100 Mbps (TCLink)
- Remote Ryu controller at 127.0.0.1:6633

---

## SDN Logic & Flow Rule Design

### Controller behaviour
1. **Table-miss flow** installed on switch connect — sends unknown packets to controller (priority 0)
2. **Packet-in handler** implements a learning switch — learns source MAC → port mapping and installs unicast flow rules (priority 1, idle_timeout=30s, hard_timeout=120s)
3. **Monitoring loop** runs every 5 seconds — sends `OFPPortStatsRequest` and `OFPFlowStatsRequest` to every connected switch
4. **Port stats reply handler** calculates bandwidth:

```
BW (kbps) = (current_bytes - previous_bytes) × 8 / elapsed_seconds / 1000
```

### OpenFlow messages used
| Message | Direction | Purpose |
|---|---|---|
| OFPSwitchFeatures | Switch → Controller | Handshake on connect |
| OFPFlowMod | Controller → Switch | Install flow rules |
| OFPPacketIn | Switch → Controller | Unknown packet forwarding |
| OFPPacketOut | Controller → Switch | Forward current packet |
| OFPPortStatsRequest | Controller → Switch | Poll port byte counters |
| OFPPortStatsReply | Switch → Controller | Return TX/RX byte counts |
| OFPFlowStatsRequest | Controller → Switch | Poll flow table |
| OFPFlowStatsReply | Switch → Controller | Return per-flow stats |

---

## Setup & Installation

### Requirements
- Ubuntu 20.04 / 22.04 (VirtualBox VM works)
- Python 3.8 (for Ryu — see note below)
- Mininet
- Open vSwitch
- iperf / iperf3
- Wireshark (optional, for packet capture)

### Step 1 — Install Mininet
```bash
sudo apt update
sudo apt install mininet -y
```

### Step 2 — Install Python 3.8 and create Ryu virtual environment
```bash
# If python3.8 not available, add deadsnakes PPA first
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.8 python3.8-dev python3.8-venv -y

# Create the virtual environment
python3.8 -m venv ryu-env
source ryu-env/bin/activate

# Pin eventlet to avoid import error, then install Ryu
pip install eventlet==0.30.2
pip install ryu
```

### Step 3 — Clone this repository
```bash
git clone https://github.com/YOUR_USERNAME/network-utilization-monitor.git
cd network-utilization-monitor
```

---

## Execution Steps

Open **two terminals** in the project directory.

**Terminal 1 — Start Ryu controller:**
```bash
source ryu-env/bin/activate
ryu-manager monitor_controller.py
```

**Terminal 2 — Start Mininet topology:**
```bash
sudo python3 topology.py
```

Wait for the Mininet CLI prompt (`mininet>`), then run test scenarios below.

---

## Test Scenarios

### Scenario 1 — Basic connectivity (ping)
```
mininet> pingall
mininet> h1 ping h3 -c 10
```
**Expected output:** All hosts reachable, Ryu terminal shows small BW values updating every 5s.

### Scenario 2 — High bandwidth traffic (iperf)
```
mininet> h3 iperf -s &
mininet> h1 iperf -c 10.0.0.3 -t 20
```
**Expected output:** Ryu terminal shows port bandwidth spike to several Mbps on s1 and s2 inter-switch link.

### Scenario 3 — Multiple parallel flows
```
mininet> h4 iperf -s &
mininet> h2 iperf -c 10.0.0.4 -t 15 &
mininet> h1 iperf -c 10.0.0.3 -t 15
```
**Expected output:** Per-port utilization visible on both switches simultaneously, flow table grows.

### Check flow tables directly
```
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
mininet> sh ovs-ofctl -O OpenFlow13 dump-ports s1
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s2
```

---

## Expected Output

### Ryu controller terminal (every 5 seconds)
```
=== Port Bandwidth Report — Switch 1 ===
Port   TX bytes     RX bytes     TX kbps        RX kbps
------------------------------------------------------------
1      104857600    52428800     84234.56       42117.28
2      52428800     104857600    42117.28       84234.56
3      2048         1024         3.28           1.64
============================================================
--- Flow Table: Switch 1 ---
  priority=1   match=OFPMatch(...)   packets=1024   bytes=104857600
```

### Mininet ping output
```
*** Ping: testing ping reachability
h1 -> h2 h3 h4
h2 -> h1 h3 h4
h3 -> h1 h2 h4
h4 -> h1 h2 h3
*** Results: 0% dropped (12/12 received)
```

### iperf output
```
------------------------------------------------------------
Client connecting to 10.0.0.3, TCP port 5001
[ ID] Interval       Transfer     Bandwidth
[  3]  0.0-20.0 sec  2.20 GBytes   943 Mbits/sec
```

---

## Proof of Execution

Screenshots are included in the `/screenshots` folder:

| File | Description |
|---|---|
| `pingall.png` | All hosts reachable via pingall |
| `ryu_bw_output.png` | Ryu terminal showing live bandwidth readings |
| `iperf_result.png` | iperf throughput test result |
| `flow_table_s1.png` | ovs-ofctl dump-flows s1 output |
| `dump_ports_s1.png` | ovs-ofctl dump-ports s1 output |
| `wireshark.png` | Wireshark capture of OpenFlow stats messages |

---

## Performance Analysis

| Metric | Tool | Observation |
|---|---|---|
| Latency | ping | ~0.2ms intra-switch, ~0.5ms inter-switch |
| Throughput | iperf | ~940 Mbps on 100Mbps links (virtual) |
| Flow table | ovs-ofctl | Rules installed dynamically, expire on idle |
| Bandwidth | Ryu stats | Updated every 5s, calculated from delta bytes |

---

## References

1. Ryu SDN Framework — https://ryu.readthedocs.io
2. Mininet Documentation — http://mininet.org/walkthrough/
3. OpenFlow 1.3 Specification — https://opennetworking.org/wp-content/uploads/2014/10/openflow-spec-v1.3.0.pdf
4. Open vSwitch Documentation — https://docs.openvswitch.org
5. Mininet Python API — https://mininet.org/api/
