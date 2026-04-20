from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (CONFIG_DISPATCHER, MAIN_DISPATCHER,
                                     DEAD_DISPATCHER, set_ev_cls)
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.lib import hub
import time

POLL_INTERVAL = 5  # seconds between each stats poll


class NetworkMonitor(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(NetworkMonitor, self).__init__(*args, **kwargs)
        self.mac_to_port = {}       # {dpid: {mac: port}}
        self.datapaths = {}         # {dpid: datapath}
        self.port_stats_prev = {}   # {(dpid, port): bytes} for BW calc
        self.port_stats_time = {}   # {(dpid, port): timestamp}
        self.monitor_thread = hub.spawn(self._monitor_loop)

    # ──────────────────────────────────────────────────────────────────────────
    # Switch feature handshake — install table-miss flow entry
    # ──────────────────────────────────────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp     = ev.msg.datapath
        ofp    = dp.ofproto
        parser = dp.ofproto_parser

        # Table-miss: send every unknown packet to controller
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                          ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, priority=0, match=match, actions=actions)
        self.logger.info("Switch %s connected — table-miss flow installed", dp.id)

    # ──────────────────────────────────────────────────────────────────────────
    # Track connected / disconnected switches
    # ──────────────────────────────────────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
            self.logger.info("Switch registered: dpid=%s", dp.id)
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)
            self.logger.info("Switch removed: dpid=%s", dp.id)

    # ──────────────────────────────────────────────────────────────────────────
    # Monitoring loop — polls every POLL_INTERVAL seconds
    # ──────────────────────────────────────────────────────────────────────────
    def _monitor_loop(self):
        while True:
            for dp in list(self.datapaths.values()):
                self._request_port_stats(dp)
                self._request_flow_stats(dp)
            hub.sleep(POLL_INTERVAL)

    def _request_port_stats(self, dp):
        parser = dp.ofproto_parser
        req = parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY)
        dp.send_msg(req)

    def _request_flow_stats(self, dp):
        parser = dp.ofproto_parser
        req = parser.OFPFlowStatsRequest(dp)
        dp.send_msg(req)

    # ──────────────────────────────────────────────────────────────────────────
    # Port stats reply — calculates bandwidth per port
    # ──────────────────────────────────────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        now  = time.time()

        self.logger.info("")
        self.logger.info("=== Port Bandwidth Report — Switch %s ===", dpid)
        self.logger.info("%-6s %-12s %-12s %-14s %-14s",
                         "Port", "TX bytes", "RX bytes", "TX kbps", "RX kbps")
        self.logger.info("-" * 60)

        for stat in ev.msg.body:
            port = stat.port_no
            if port > 65000:   # skip LOCAL port
                continue

            key_tx = (dpid, port, 'tx')
            key_rx = (dpid, port, 'rx')

            prev_tx   = self.port_stats_prev.get(key_tx, 0)
            prev_rx   = self.port_stats_prev.get(key_rx, 0)
            prev_time = self.port_stats_time.get((dpid, port), now)

            elapsed = now - prev_time if now != prev_time else POLL_INTERVAL

            # Bandwidth in kbps = delta_bytes * 8 / elapsed / 1000
            tx_kbps = (stat.tx_bytes - prev_tx) * 8 / elapsed / 1000
            rx_kbps = (stat.rx_bytes - prev_rx) * 8 / elapsed / 1000

            self.logger.info("%-6s %-12d %-12d %-14.2f %-14.2f",
                             port, stat.tx_bytes, stat.rx_bytes,
                             tx_kbps, rx_kbps)

            # Save current values for next poll
            self.port_stats_prev[key_tx]      = stat.tx_bytes
            self.port_stats_prev[key_rx]      = stat.rx_bytes
            self.port_stats_time[(dpid, port)] = now

        self.logger.info("=" * 60)

    # ──────────────────────────────────────────────────────────────────────────
    # Flow stats reply — shows per-flow packet/byte counts
    # ──────────────────────────────────────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        self.logger.info("--- Flow Table: Switch %s ---", dpid)
        for flow in ev.msg.body:
            if flow.priority == 0:
                continue   # skip table-miss entry
            self.logger.info(
                "  priority=%-3s match=%-40s packets=%-6d bytes=%d",
                flow.priority, str(flow.match), flow.packet_count, flow.byte_count
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Packet-in handler — learning switch logic
    # ──────────────────────────────────────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg     = ev.msg
        dp      = msg.datapath
        ofp     = dp.ofproto
        parser  = dp.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return

        # Drop LLDP
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst  = eth.dst
        src  = eth.src
        dpid = dp.id

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port  # learn source MAC

        # Decide output port
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofp.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # Install a flow rule so future packets don't hit controller
        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self._add_flow(dp, priority=1, match=match, actions=actions,
                           idle_timeout=30, hard_timeout=120)

        # Send the current packet out
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        out  = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id,
            in_port=in_port, actions=actions, data=data
        )
        dp.send_msg(out)

    # ──────────────────────────────────────────────────────────────────────────
    # Helper — install a flow rule
    # ──────────────────────────────────────────────────────────────────────────
    def _add_flow(self, dp, priority, match, actions,
                  idle_timeout=0, hard_timeout=0):
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        inst   = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod    = parser.OFPFlowMod(
            datapath=dp, priority=priority, match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout
        )
        dp.send_msg(mod)
