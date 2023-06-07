#Author Ondrej Lukas - ondrej.lukas@aic.fel.cvut.cz
# Library of helpful functions and objects to play the net sec game
from collections import namedtuple
import netaddr
import json
from dataclasses import dataclass, field





# Transitions are not implemented in the game of 2022
# Transition between nodes
"""
Transition represents generic actions for attacker in the game. Each transition has a default probability
of success and probability of detection (if the defender is present). Each transition has default cost and reward (if successful).
Net reward can be computed as follows net_reward = p_sucess * (default_reward - default_cost)
"""
Transition = namedtuple("Transition", ["type", "default_success_p", "default_detection_p", "default_reward", "default_cost"])

# List of transitions available for attacker with default parameters
transitions = {
    #"ScanNetwork": Transition("ScanNetwork", 0.9, 0.025, 0,1), 
    #"FindServices": Transition("FindServices",0.9, 0.035,0,1),
    #"FindData": Transition("FindData",0.8, 0.012, 0, 1),
    #"ExecuteCodeInService": Transition("ExecuteCodeInService", 0.7, 0.05, 0, 1),
    #"ExfiltrateData": Transition("ExfiltrateData",0.8, 0.012, 0, 1),
    "ScanNetwork": Transition("ScanNetwork", 0.9, 0.2, 0,1), 
    "FindServices": Transition("FindServices",0.9, 0.3,0,1),
    "FindData": Transition("FindData",0.8, 0.1, 0, 1),
    "ExecuteCodeInService": Transition("ExecuteCodeInService", 0.7, 0.4, 0, 1),
    "ExfiltrateData": Transition("ExfiltrateData",0.8, 0.1, 0, 1),
}

#Actions
"""
Actions are composed of the transition type (see Transition) and additional parameters listed in dictionary
 - ScanNetwork {"target_network": "X.X.X.X/mask" (string)}
 - FindServices {"target_host": "X.X.X.X" (string)}
 - FindData {"target_host": "X.X.X.X" (string)}
 - ExecuteCodeInService {"target_host": "X.X.X.X" (string), "target_service":"service" (Service named tuple)}
 - ExfiltrateData {"target_host": "X.X.X.X" (string), "source_host":"X.X.X.X" (string), "data":"Data tuple" (tuple)}
"""
class Action(object):
  
    def __init__(self, transition:str, params:dict) -> None:
        self._transition_name = transition
        self._parameters = params
    
    @property
    def transition(self) -> Transition:
        return transitions[self._transition_name]
    @property
    def parameters(self)->dict:
        return self._parameters
    def __str__(self) -> str:
        return f"Action <{self._transition_name}|{self.parameters}>"
    
    def __eq__(self, __o: object) -> bool:
        if isinstance(__o, Action):
            return self.transition == __o.transition and self.parameters == __o.parameters
        return False
    def __hash__(self) -> int:
        return hash(self.transition) + hash("".join(self.parameters))


# Observation - given to agent after taking an action
"""
Observations are given when making a step in the environment.
 - observation: current state of the environment
 - reward: float  value with immediate reward for last step
 - done: boolean, True if the game ended. 
    No further interaction is possible (either terminal state or because of timeout)
 - info: dict, can contain additional information about the reason for ending
"""
Observation = namedtuple("Observation", ["state", "reward", "done", "info"])

# Service - agents representation of a service found with "FindServices" action
Service = namedtuple("Service", ["name", "type", "version", "is_local"])


"""
Game state represents the states in the game state space.
"""
@dataclass(frozen=True)
class GameState(object):
    controlled_hosts:set=field(default_factory=set, hash=True)
    known_hosts:set=field(default_factory=set,  hash=True)
    known_services:dict=field(default_factory=dict, hash=True)
    known_data:dict=field(default_factory=dict,  hash=True)
    known_networks:set=field(default_factory=set,  hash=True)
    
    @property
    def as_graph(self):
        node_types = {"network":0, "host":1, "service":2, "datapoint":3}
        graph_nodes = {}
        node_features = []
        controlled = []
        try:
            edges = []
            #add known nets
            for net in self.known_networks:
                graph_nodes[net] = len(graph_nodes)
                node_features.append(node_types["network"])
                controlled.append(0)
            #add known and controlled hosts
            for host in self.known_hosts:
                graph_nodes[host] = len(graph_nodes)
                node_features.append(node_types["host"])
                #add to controlled hosts if needed
                if host in self.controlled_hosts:
                    controlled.append(1)
                else:
                    controlled.append(0)
                #add to proper network if host is in the network
                try:
                    for net in self.known_networks:
                        if host in netaddr.IPNetwork(net):
                            edges.append((graph_nodes[net], graph_nodes[host]))
                            edges.append((graph_nodes[host], graph_nodes[net]))
                except netaddr.core.AddrFormatError as e:
                    print(host, self.known_networks, self.known_hosts, net)
                    print("Error:")
                    print(e)
                    exit()
            #Add known services
            for host,services in self.known_services.items():
                for service in services:
                    graph_nodes[service] = len(graph_nodes)
                    node_features.append(node_types["service"])
                    controlled.append(0)
                    #connect to the proper host
                    try:
                        edges.append((graph_nodes[host], graph_nodes[service]))
                        edges.append((graph_nodes[service], graph_nodes[host]))
                    except KeyError as e:
                        print(self.known_hosts)
                        print(self.known_services)
                        raise e
            #Add known data
            for host,data in self.known_data.items():
                for datapoint in data:
                    graph_nodes[datapoint] = len(graph_nodes)
                    node_features.append(node_types["datapoint"])
                    controlled.append(0)
                    #connect to the proper host
                    edges.append((graph_nodes[host], graph_nodes[datapoint]))
                    edges.append((graph_nodes[datapoint], graph_nodes[host]))

            #print(f"Total Nodes:{total_nodes}")
        except KeyError as e:
            print(f"Error in building graph from {self}: {e}")
        return node_features, controlled, edges, {v:k for k,v in graph_nodes.items()}

    def __str__(self) -> str:
        return f"State<nets:{self.known_networks}; known:{self.known_hosts}; owned:{self.controlled_hosts}; services:{self.known_services}; data:{self.known_data}>"
    
    
    def as_json(self):
        d = {"nets":list(self.known_networks), "known_hosts":list(self.known_hosts), "controlled_hosts":list(self.controlled_hosts), "known_services":list(self.known_services.items()), "known_data":list(self.known_data.items())}
        return json.dumps(d) 

# Main is only used for testing
if __name__ == '__main__':
    # Used for tests

    a = Action("FindServices", ["192.168.1.0"])
    a2 = Action("FindServices", ["192.168.1.0"])
    #print(hash(a), hash(a2))
    # # print(a1, a2, a1==a2)
    s1 = GameState({"192.168.1.0"}, {}, {'213.47.23.195': {Service(name='bash', type='passive', version='5.0.0', is_local=True), Service(name='listener', type='passive', version='1.0.0', is_local=False)}},{},{})
    #print(hash(s1))
    s2 = GameState({"192.168.1.0"}, {}, {'213.47.23.195': {Service(name='listener', type='passive', version='1.0.0', is_local=False)}},{},{})
    s3 = GameState({"192.168.1.0"}, {}, {'213.47.23.195': {Service(name='listener', type='passive', version='1.2.0', is_local=False)}},{},{})
    print(s1==s2, s2==s2, s2 == s3)
    s1.known_services["213.47.23.195"] = "new_value"
    print(s1)
    