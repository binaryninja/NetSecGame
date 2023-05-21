#Author: Ondrej Lukas - ondrej.lukas@aic.fel.cvut.cz
import netaddr
from random import random
from game_components import *
import yaml
from random import choice, seed
import random
import copy
from cyst.api.configuration import *
import numpy as np
#from scenarios.scenario_configuration import *
import scenarios.scenario_configuration
import scenarios.smaller_scenario_configuration
import scenarios.tiny_scenario_configuration
import logging


# Set the logging
logger = logging.getLogger('Net-sec-env')
    

class Network_Security_Environment(object):
    def __init__(self, random_start=True, verbosity=0) -> None:
        self._nodes = {}
        self._connections = {}
        self._ips = {}
        self._exploits = {}
        self._fw_rules = []
        self._random_start = random_start

        self._defender_placements = None
        self._current_state = None
        self._done = False
        self._src_file = None
        self.verbosity = verbosity
        self._detected = False
    
    @property
    def current_state(self) -> GameState:
        return self._current_state

    @property
    def timestamp(self)->int:
        return self._step_counter

    @property
    def done(self):
        return self._done
    
    @property
    def detected(self):
        if self.done: #Only tell if detected when the interaction ends
            return self._detected
        else: return False
    
    @property
    def num_actions(self):
        return len(transitions)
    
    def get_all_actions(self):
        actions = {}
        for ip, name in self._ips.items():
            #network scans
            for net in self._get_networks_from_host(ip):
                actions[len(actions)] = Action("ScanNetwork",{"target_network":net})
            #portscans
            actions[len(actions)] = Action("FindServices", {"target_host":ip})

            #Run Code in service
            for service in self._get_services_from_host(ip):
                actions[len(actions)] = Action("ExecuteCodeInService", {"target_host":ip, "target_service":service.name})
            #find data
            actions[len(actions)] = Action("FindData", {"target_host":ip})

            #exfiltrate data
            for data in self._get_data_in_host(ip):
                for src in self._ips.keys():
                    for trg in self._ips.keys():
                        actions[len(actions)] = Action("ExfiltrateData", {"target_host":trg, "data":data, "source_host":src})
        return actions

    def initialize(self, win_conditons:dict, defender_positions:dict, attacker_start_position:dict, max_steps=10, agent_seed=False)-> Observation:
        """
        Initializes the environment with start and goal configuraions.
        Entities in the environment are either read from CYST objects directly or from the serialization file.
        TODO Firewall rules processing
        """
        # Set the seed if passed by the agent
        if agent_seed:
            np.random.seed(agent_seed)
            random.seed(agent_seed)
            logger.info(f'Agent passed a seed, setting to {agent_seed}')
    
    def _create_starting_state(self) -> GameState:
        """
        Builds the starting GameState. Currently, we artificially extend the knonw_networks with +- 1 in the third octet.
        """
        if self._random_start:
            controlled_hosts = set()
            for h in self._attacker_start_position["controlled_hosts"]:
                if "/" in h: #possible network
                    hosts = [str(ip) for ip in netaddr.IPNetwork(h) if (str(ip) in self._ips.keys() and isinstance(self._nodes[self._ips[str(ip)]], NodeConfig))]
                    controlled_hosts.add(choice(hosts))
                else:
                    controlled_hosts.add(h)
        else:
            controlled_hosts = self._attacker_start_position["controlled_hosts"]
        known_networks = set()
        #Exted the networks with the neighbouring networks
        for h in controlled_hosts:
            for net in self._get_networks_from_host(h): #TODO
                known_networks.add(str(net))
                if net.is_private(): #TODO
                    net.value += 256
                    if net.is_private():
                        known_networks.add(str(net))
                    net.value -= 2*256
                    if net.is_private():
                        known_networks.add(str(net))
                    #return value back to the original
                    net.value += 256

        known_hosts = self._attacker_start_position["known_hosts"].union(controlled_hosts)

        return GameState(controlled_hosts, known_hosts, self._attacker_start_position["known_services"],self._attacker_start_position["known_data"], known_networks)
    
    def _place_defences(self, placements:dict)->None:
        # TODO
        if placements:
            self._defender_placements = True
        else:
            self._defender_placements = False
        # assert self._defender_placements ==  None
        # self._defender_placements = placements
    
    def read_topology(self, filename) -> None:
        """
        Method to process YAML file with congifuration from CYST and build a state space of the environment with possible transitions.
        """
        with open(filename, "r") as stream:
            try:
                data = yaml.safe_load(stream)
                for k,v in data.items():
                    if v['cls_type'] in ["NodeConfig", "RouterConfig"]: #new node or router in the network
                        self._nodes[v['id']] = v
                        self._connections[v['id']] = []
                        #add network information
                        for item in v["interfaces"]:
                            if item["cls_type"] == "InterfaceConfig":
                                # if item["net"]["cls_type"] == "IPNetwork":
                                #     if item["net"]["value"] not in self._networks.keys():
                                #         self._networks[item["net"]["value"]] = []
                                # self._networks[item["net"]["value"]].append((item["ip"]["value"], v['id']))
                                # #add IP-> host name mapping
                                self._ips[item["ip"]["value"]] = v['id']  
                    elif v['cls_type'] in "ConnectionConfig": # TODO
                        self._connections[v["src_id"]].append(v["dst_id"])
                        self._connections[v["dst_id"]].append(v["src_id"])
            except yaml.YAMLError as e:
                print(e)
        self._src_file = filename

    def process_cyst_config(self, configuration_objects:list)->None:
        nodes = []
        node_to_id = {}
        routers = []
        connections = []
        exploits = []
        
        #sort objects into categories
        for o in configuration_objects:
            if isinstance(o, NodeConfig):
                nodes.append(o)
            elif isinstance(o, RouterConfig):
                routers.append(o)    
            elif isinstance(o, ConnectionConfig):
                connections.append(o)
            elif isinstance(o, ExploitConfig):
                exploits.append(o)
        #process Nodes
        for n in nodes:
            #print(n)
            self._nodes[n.id] = n
            node_to_id[n.id] = len(node_to_id)
    
            for i in n.interfaces:
                self._ips[str(i.ip)] = n.id
        #process routers
        for r in routers:
            self._nodes[r.id] = r
            node_to_id[r.id] = len(node_to_id)
            for i in r.interfaces:
                self._ips[str(i.ip)] = r.id
            #add Firewall rules
            for tp in r.traffic_processors:
                for chain in tp.chains:
                    for rule in chain.rules:
                        if rule.policy == FirewallPolicy.ALLOW:
                            self._fw_rules.append(rule)
        #connections
        self._connections = np.zeros([len(node_to_id),len(node_to_id)])
        for c in connections:
            self._connections[node_to_id[c.src_id],node_to_id[c.dst_id]] = 1
        #exploits
        self._exploits = exploits   
    
    def get_valid_actions(self, state:GameState)->list:
        """
        Returns list of valid actions in a given state.
        """
        actions = []
        #Scan network
        for net in state.known_networks:
            actions.append(Action("ScanNetwork",{"target_network":net}))
        #Find services
        for host in state.known_hosts:
            actions.append(Action("FindServices", {"target_host":host}))
        #Find Data
        for host in state.known_hosts.union(state.controlled_hosts):
            a = Action("FindData", {"target_host":host})
            if a not in actions:
                actions.append(a)
        #ExecuteCodeInService
        for host, services in state.known_services.items():
            for s in services:
                actions.append(Action("ExecuteCodeInService", {"target_host":host, "target_service":s.name}))
        #ExfiltrateData
        for source, data in state.known_data.items():
            for target in state.controlled_hosts:
                if source != target and len(data) > 0:
                    for d in data:
                        actions.append(Action("ExfiltrateData", {"target_host":target, "data":d, "source_host":source}))
        return actions

    def _get_services_from_host(self, host_ip)-> set:
        """
        Returns set of Service tuples from given hostIP
        TODO active services
        """
        try:
            # Check if the IP has a correct IP format
            netaddr.IPAddress(host_ip)
            # Do we have this IP in our list of ips?
            if host_ip in self._ips:
                # Get the information we have about this ip
                host = self._nodes[self._ips[host_ip]]
                services = set()
                # Is the host of type NodeConfig?
                if isinstance(host, NodeConfig):
                    for service in host.passive_services:
                        if service.local:
                            if host_ip in self._current_state.controlled_hosts:
                                services.add(Service(service.type, "passive", service.version))
                        else:
                            services.add(Service(service.type, "passive", service.version))
                return services
            # Return empty services
            return {}
        except (ValueError, netaddr.core.AddrFormatError) as error:
            logging.error("HostIP is invalid. Due to {error}")
            # Return empty services
            return {}
    
    def _get_networks_from_host(self, host_ip)->set:
        try:
            host = self._ips[host_ip]
        except KeyError:
            print(f"Given host IP '{host_ip}' is unknown!")
        networks = set()
        for interface in self._nodes[host].interfaces:
            if isinstance(interface, InterfaceConfig):
                networks.add(interface.net)
        #print(host_ip, networks, self._nodes[host].interfaces)
        return networks
    
    def _get_data_in_host(self, host_ip)->list:
        data = set()
        if host_ip in self._ips:
            host = self._nodes[self._ips[host_ip]]
            if isinstance(host, NodeConfig):
                for service in host.passive_services:
                    try:
                        for d in service.private_data:
                            data.add((d.owner, d.description))
                    except AttributeError:
                        pass
                        #service does not contain any data
        return data

    def _execute_action(self, current:GameState, action:Action)-> GameState:

        if action.transition.type == "ScanNetwork":
            #does the network exist?
            new_ips = set()
            # Read all the theoretically possible IPs in a network
            for ip in netaddr.IPNetwork(action.parameters["target_network"]):
                # If any of those IPs is in our list of known IPs, return it
                if str(ip) in self._ips.keys():
                    new_ips.add(str(ip))

            # Add the IPs in the network to the list of known hosts
            extended_hosts = current.known_hosts.union(new_ips)
            return GameState(current.controlled_hosts, extended_hosts, current.known_services, current.known_data, current.known_networks)

        elif action.transition.type == "FindServices":
            found_services =  self._get_services_from_host(action.parameters["target_host"])
            extended_services = {k:v for k,v in current.known_services.items()}
            if len(found_services) > 0:
                if action.parameters["target_host"] not in extended_services.keys():
                    extended_services[action.parameters["target_host"]] = frozenset(found_services)
                else:
                    extended_services[action.parameters["target_host"]] = frozenset(extended_services[action.parameters["target_host"]]).union(found_services)
            return GameState(current.controlled_hosts, current.known_hosts, extended_services, current.known_data, current.known_networks)
        elif action.transition.type == "FindData":
            extended_data = {k:v for k,v in current.known_data.items()}
            new_data = self._get_data_in_host(action.parameters["target_host"])
            if len(new_data) > 0:
                if action.parameters["target_host"] not in extended_data.keys():
                    extended_data[action.parameters["target_host"]] = new_data
                else:
                    extended_data[action.parameters["target_host"]].union(new_data)
            return GameState(current.controlled_hosts, current.known_hosts, current.known_services, extended_data, current.known_networks)
        
        elif action.transition.type == "ExecuteCodeInService":
            extended_controlled_hosts = set([x for x in current.controlled_hosts])
            if action.parameters["target_host"] not in current.controlled_hosts:
                extended_controlled_hosts.add(action.parameters["target_host"])
            new_networks = self._get_networks_from_host(action.parameters["target_host"])
            extended_networks = current.known_networks.union(new_networks)
            return GameState(extended_controlled_hosts, current.known_hosts, current.known_services, current.known_data, extended_networks)
        
        elif action.transition.type == "ExfiltrateData":
            extended_data = {k:v for k,v in current.known_data.items()}
            if len(action.parameters["data"]) > 0:
                if action.parameters["target_host"] not in current.known_data.keys():
                    extended_data[action.parameters["target_host"]] = {action.parameters["data"]}
                else:
                    extended_data[action.parameters["target_host"]].union(action.parameters["data"])
            return GameState(current.controlled_hosts, current.known_hosts, current.known_services, extended_data, current.known_networks)
        else:
            raise ValueError(f"Unknown Action type: '{action.transition.type}'")
    
    def is_valid_action(self, state:GameState, action:Action)-> bool:
        if action.transition.type == "ScanNetwork":
            try:
                net = netaddr.IPNetwork(action.parameters["target_network"])
                return True
            except netaddr.core.AddrFormatError:
                return False
        elif action.transition.type == "FindServices":
            target = action.parameters["target_host"]
            accessible = [target in netaddr.IPNetwork(n) for n in state.known_networks] #TODO Add check for FW rules
            return action.parameters["target_host"] in self._ips and any(accessible)
        elif action.transition.type == "FindData":
            return action.parameters["target_host"] in state.controlled_hosts or action.parameters["target_host"] in state.known_hosts
        elif action.transition.type == "ExecuteCodeInService":
            return action.parameters["target_host"] in state.known_services and action.parameters["target_service"] in [x.name for x in state.known_services[action.parameters["target_host"]]]
        elif action.transition.type == "ExfiltrateData":
            if action.parameters["source_host"] in state.controlled_hosts or action.parameters["source_host"] in state.known_hosts:
                try:
                    data_accessible = action.parameters["data"] in state.known_data[action.parameters["source_host"]]
                    target = action.parameters["target_host"]
                    target_accessible = [target in netaddr.IPNetwork(n) for n in state.known_networks] #TODO Add check for FW rules
                    return data_accessible and target_accessible  and len(action.parameters["data"]) > 0
                except KeyError as e:
                    #print(e)
                    return False
            else:
                return False #for now we don't support this option TODO
        else:
            print(f"Unknown transition type '{action.transition.type}'")
            return False
    
    def is_goal(self, state:GameState)->bool:
        #check if all netoworks are known
        networks = set(self._win_conditions["known_networks"]) <= set(state.known_networks) 
        known_hosts = set(self._win_conditions["known_hosts"]) <= set(state.known_hosts)
        controlled_hosts = set(self._win_conditions["controlled_hosts"]) <= set(state.controlled_hosts)
        try:
            services = True
            keys_services = [k for k in self._win_conditions["known_services"].keys() if k not in state.known_services]
            if len(keys_services) == 0:
                for k in self._win_conditions["known_services"].keys():
                    for s in self._win_conditions["known_services"][k]:
                        if s not in state.known_services[k]:
                            services = False
                            break

            else:
                services = False
        except KeyError:
            services = False
        
        try:
            data = True
            keys_data = [k for k in self._win_conditions["known_data"].keys() if k not in state.known_data]
            if len(keys_data) == 0:
                for k in self._win_conditions["known_data"].keys():
                    if not set(self._win_conditions["known_data"][k]) <= set(state.known_data[k]):
                        data = False
                        break

            else:
                data = False
        except KeyError:
            data = False
        if self.verbosity > 1:
            print("networks", networks)
            print("known", known_hosts)
            print("controlled", controlled_hosts)
            print("services", services)
            print("data", data)
        return networks and known_hosts and controlled_hosts and services and data
    
    def _is_detected(self, state, action:Action)->bool:
        if self._defender_placements:
            value = random.random() < action.transition.default_detection_p     
            logger.info(f'There is a defender and the detection is {value}')
            return value
        else: #no defender
            logger.info(f'There is NO defender')
            return False 
    
    def reset(self)->Observation:
        """
        Function to reset the state of the game 
        and play a new episode
        """
        logger.info(f'------Game resetted. New startging ------')
        self._done = False
        self._step_counter = 0
        self.detected = False  
        self._current_state = self._create_starting_state()
        return Observation(self._current_state, 0, self._done, {})
    
    def step(self, action:Action)-> Observation:
        """
        Take a step in the environment given an action

        in:
        - action
        out:
        - observation of the state of the env
        """
        if not self._done:
            logger.info(f'Step taken')
            self._step_counter += 1

            reason = {}
            # 1. Check if the action was successful or not
            if random.random() <= action.transition.default_success_p:
                # The action was successful
                logger.info(f'Action {action} sucessful')

                # Get the next state given the action
                next_state = self._execute_action(self._current_state, action)

                # Reard for making an action
                reward = -1     #action.transition.default_reward - action.transition.default_cost
            else: 
                # The action was not successful
                logger.info(f'Action {action} not sucessful')

                # State does not change
                next_state = self._current_state

                # Reward for taking an action
                reward = -1 #action.transition.default_cost

                if self.verbosity >=1:
                    print("Action unsuccessful")

            # 2. Check if the new state is the goal state
            is_goal = self.is_goal(next_state)
            if is_goal:
                # It is the goal
                # Give reward
                reward += 100  
                logger.info(f'Goal reached')
                # Game ended
                self._done = True
                logger.info(f'Game ended')
                reason = {'end_reason':'goal_reached'}

            # 3. Check if the action was detected
            detected = self._is_detected(self._current_state, action)
            if detected:
                logger.info(f'Action detected')
                # Reward should be negative
                reward -= 50
                # Mark the environment as detected
                self.detected = True
                reason = {'end_reason':'detected'}
                self._done = True
                logger.info(f'Game ended')

            # 4. Check if the max number of steps of the game passed already
            if self._step_counter >= self.max_steps:
                logger.info(f'Game timeout')
                self._done = True
                logger.info(f'Game ended')
                reason = {'end_reason':'timeout'}

            # Make the state we just got into, our current state
            self._current_state = next_state

            # Return an observation
            return Observation(next_state, reward, self._done, reason)
        else:
            raise ValueError("Interaction over! No more steps can be made in the environment")


if __name__ == "__main__":
    # Create the network security environment
    env = Network_Security_Environment(random_start=True, verbosity=0)
    
    # Read network setup from predefined CYST configuration
    env.process_cyst_config(scenarios.scenario_configuration.configuration_objects)

    # Test random data and start position
    goal = {
        "known_networks":set(),
        "known_hosts":set(),
        "controlled_hosts":set(),
        "known_services":{},
        "known_data":{"213.47.23.195":"random"}
    }
    attacker_start = {
        "known_networks":set(),
        "known_hosts":set(),
        "controlled_hosts":{"213.47.23.195","192.168.2.0/24"},
        "known_services":{},
        "known_data":{}
    }

    # Test normal winning conditions and starting position
    """
    goal = {
        "known_networks":set(),
        "known_hosts":{},
        "controlled_hosts":{},
        "known_services":{},
        "known_data":{"213.47.23.195":{("User1", "DataFromServer1"),("User1", "DatabaseData")}}
    }

    # Define where the attacker will start
    attacker_start = {
        "known_networks":set(),
        "known_hosts":set(),
        "controlled_hosts":{"192.168.2.2", "213.47.23.195"},
        "known_services":{'213.47.23.195': [Service(name='listener', type='passive', version='1.0.0'), Service(name='bash', type='passive', version='5.0.0')]},
        "known_data":{"213.47.23.195":{("User1", "DataFromServer1"),("User1", "DatabaseData")}}
    }
    """

    # Do we have a defender? 
    defender = True

    # Initialize the game
    state_1 = env.initialize(win_conditons=goal, defender_positions=defender, attacker_start_position=attacker_start, max_steps=50, agent_seed=42)
    print(state_1)
    env.get_all_actions()
    print(state_1.controlled_hosts)
