from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.topo import Topo
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink

class MonitorTopo(Topo):
    def build(self):
        # Add 2 switches
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')

        # Add 4 hosts
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
        h4 = self.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')

        # Host-switch links (100Mbps)
        self.addLink(h1, s1, bw=100)
        self.addLink(h2, s1, bw=100)
        self.addLink(h3, s2, bw=100)
        self.addLink(h4, s2, bw=100)

        # Inter-switch link (100Mbps)
        self.addLink(s1, s2, bw=100)

def run():
    setLogLevel('info')
    topo = MonitorTopo()
    net = Mininet(
        topo=topo,
        controller=RemoteController,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=False
    )
    net.start()

    # Force OpenFlow 1.3 on all switches
    for sw in net.switches:
        sw.cmd('ovs-vsctl set bridge {} protocols=OpenFlow13'.format(sw.name))

    print("\n*** Network Utilization Monitor Topology ***")
    print("Hosts: h1(10.0.0.1), h2(10.0.0.2), h3(10.0.0.3), h4(10.0.0.4)")
    print("Switches: s1 <--> s2")
    print("Controller: RemoteController at 127.0.0.1:6633")
    print("*" * 50)

    CLI(net)
    net.stop()

if __name__ == '__main__':
    run()
