# Author Ondrej Lukas - ondrej.lukas@aic.fel.cvut.cz

import sys
import os
import asyncio
import requests
import json
import copy


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from game_components import GameState, Action, ActionType, GameStatus, IP
from worlds.aidojo_world import AIDojoWorld
from cyst.api.environment.environment import Environment
from cyst.api.environment.platform_specification import PlatformSpecification, PlatformType
from utils.utils import get_starting_position_from_cyst_config

class CYSTWrapper(AIDojoWorld):
    """
    Class for connection CYST with the coordinator of AI Dojo
    """
    def __init__(self, task_config_file, action_queue, response_queue, cyst_objects, world_name="CYST-wrapper") -> None:
        super().__init__(task_config_file, action_queue, response_queue, world_name,)
        self.logger.info("Initializing CYST wrapper environment")
        self._id_to_cystid = {}
        self._cystid_to_id  = {}
        self._known_agent_roles = {}
        self._last_state_per_agent = {}
        self._last_action_per_agent = {}
        self._last_msg_per_agent = {}
        self._starting_positions = get_starting_position_from_cyst_config(cyst_objects)
        self._availabe_cyst_agents = {"Attacker":set([k for k in self._starting_positions.keys()])}



    async def step(self, current_state:GameState, action:Action, agent_id:tuple)-> GameState:
        """
        Executes given action in a current state of the environment and produces new GameState.
        """
        self.logger.info(f"Processing {action} from {agent_id}({self._id_to_cystid[agent_id]}) ")
        self._last_state_per_agent[agent_id] = current_state
        self._last_action_per_agent[agent_id] = action
        cyst_msg = self.action_to_cyst_message(action)
        self.logger.debug(f"Msg for cyst:{cyst_msg}")
        cyst_rsp_status, cyst_rsp_data = self._call_cyst(self._id_to_cystid[agent_id], cyst_msg)
        self.logger.info(cyst_rsp_data)

        extended_kh = copy.deepcopy(current_state.known_hosts)
        extended_kn = copy.deepcopy(current_state.known_networks)
        extended_ch = copy.deepcopy(current_state.controlled_hosts)
        extended_ks = copy.deepcopy(current_state.known_services)
        extended_kd = copy.deepcopy(current_state.known_data)
        extended_kb = copy.deepcopy(current_state.known_blocks)
        if cyst_rsp_status == 200:
            self.logger.debug("Valid response from CYST")
            new_ips = cyst_rsp_data["result"][1]["content"].split("[]")[0].strip("[]").split(",")
            self.logger.debug(new_ips)
            new_ips = filter(lambda x: x.startswith(" IPAddress"), new_ips)
            new_ips = [x for x in new_ips]
            self.logger.debug(new_ips)
            new_ips = [x.split("'")[1] for x in new_ips]
            self.logger.info(new_ips)
            for ip in new_ips:
                extended_kh.add(IP(ip))
        
        msg = (
            agent_id,
            (GameState(
                known_hosts=extended_kh,
                controlled_hosts=extended_ch,
                known_networks=extended_kn,
                known_services=extended_ks,
                known_data=extended_kd,
                known_blocks=extended_kb),
                GameStatus.OK)
            )
        self.logger.debug(f"Sending to{agent_id}: {msg}")
        await self._response_queue.put(msg)


    def create_state_from_view(self, view:dict, add_neighboring_nets:bool=True)->GameState:
        """
        Produces a GameState based on the view of the world.
        """
        # TODO: Send reset signal to cyst

    
    def reset()->None:
        """
        Resets the world to its initial state.
        """
        raise NotImplementedError

    def update_goal_descriptions(self, goal_description:str)->str:
       """
       Takes the existing goal description (text) and updates it with respect to the world.
       """
       return goal_description
    
    def update_goal_dict(self, goal_dict:dict)->dict:
        """
        Takes the existing goal dict and updates it with respect to the world.
        """
        return goal_dict
    
    def map_to_cyst(self, agent_id, agent_role):
        try:
            cyst_id = self._availabe_cyst_agents[agent_role].pop()
        except KeyError:
            cyst_id = None
        return cyst_id
    
    def action_to_cyst_message(self, action:Action)->dict:
        self.logger.debug(f"Converting action {action} to dict")
        action_dict = {
            "action":"dojo:scan_network",
            "params":
                {
                    "dst_ip":str(action.parameters["source_host"]),
                    "dst_service":"",
                    "to_network":str(action.parameters["target_network"])
                }
        }
        self.logger.debug(f"\t{action_dict}")
        return action_dict
    
    def cyst_response_to_game_state(self, str)->GameState:
        raise NotImplementedError

    def _call_cyst(self,cyst_id, msg)->dict:

        url = f"http://localhost:8282/execute/{cyst_id}/" # Replace with your server's URL
        data = msg        # The JSON data you want to send
        self.logger.info(f"Sedning request {msg} to {url}")
        try:
            # Send the POST request with JSON data
            response = requests.post(url, json=data)

            # Print the response from the server
            self.logger.debug(f'Status code:{response.status_code}')
            self.logger.debug(f'Response body:{response.text}')
            return int(response.status_code), json.loads(response.text)
        except requests.exceptions.RequestException as e:
            print(f'An error occurred: {e}')
        
    async def _process_join_game(self, agent_id, join_action)->None:
        print(f"Processing {str(join_action)} from {agent_id}")
        self.logger.debug(f"Processing {str(join_action)} from {agent_id}")
        agent_role = "Attacker"
        cyst_id = self.map_to_cyst(agent_id, agent_role)
        if cyst_id:
            self._cystid_to_id[cyst_id] = agent_id
            self._id_to_cystid[agent_id] = cyst_id
            self._known_agent_roles[agent_id] = agent_role
            kh = self._starting_positions[cyst_id]["known_hosts"]
            kn = self._starting_positions[cyst_id]["known_networks"]
            msg = (agent_id, (GameState(controlled_hosts=kh, known_hosts=kh, known_networks=kn), GameStatus.CREATED))
        else:
            msg = (agent_id, (GameState(), GameStatus.FORBIDDEN))
        self.logger.debug(f"Sending to{agent_id}: {msg}. Mapped to CYST id: {cyst_id}")
        await self._response_queue.put(msg)
        return None

    async def _process_quit_game(self, agent_id, quit_action)->None:
        print(f"Processing {str(quit_action)} from {agent_id}")
        try:
            agent_role = self._known_agent_roles[agent_id]
            cyst_id = self._id_to_cystid[agent_id]
            # remove agent's IDs
            self._known_agent_roles.pop(agent_id)
            self._id_to_cystid.pop(agent_id)
            self._cystid_to_id.pop(cyst_id)
            # make cyst_agent avaiable ag
            self._availabe_cyst_agents[agent_role].add(cyst_id)
        except KeyError:
            msg = (agent_id, (GameState(),GameStatus.BAD_REQUEST))
        msg = (agent_id, (GameState(),GameStatus.OK))
        self.logger.debug(f"Sending to{agent_id}: {msg}")
        await self._response_queue.put(msg)

    async def _process_reset(self, agent_id, game_state)->None:
        if agent_id == "world": #reset the world
            self.reset()
        else:
            msg = (agent_id, (self.create_state_from_view(game_state), GameStatus.RESET_DONE))
            self.logger.debug(f"Sending to{agent_id}: {msg}")
            await self._response_queue.put(msg)

    async def handle_incoming_action(self)->None:
        try:
            self.logger.info(f"\tStaring {self.world_name} task.")
            while True:
                agent_id, action, game_state = await self._action_queue.get()
                self.logger.debug(f"Received from{agent_id}: {action} , {game_state}.")


                # !!! TEMPORARY FIX!!!
                action_type_string = str(action.type) # TODO FIX THIS ASAP!!!!!!
                #!!!!!!!!!!!!!!!!!!!!!
                match action_type_string:
                    case "ActionType.JoinGame":
                        self.logger.debug("Before processing join game")
                        await self._process_join_game(agent_id, action)
                        self.logger.debug("After processing join game")
                    case "ActionType.QuitGame":
                        await self._process_quit_game(agent_id, action)
                    case "ActionType.ScanNetwork":
                        await self.step(game_state, action, agent_id)
                    case _:
                        raise ValueError
                # elif action.type is ActionType.QuitGame:
                #     await self._process_quit_game(agent_id, action)
                # elif action.type is ActionType.ResetGame:
                #     await self._process_reset(agent_id, game_state)
                # else:
                #     self.logger.debug(f"Normal step: {action}")
                #     await self.step(game_state, action, agent_id)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            self.logger.info(f"\t{self.world_name} Terminating by CYST wrapper by CancelledError")
            raise


if __name__ == "__main__":
    
    req_q = asyncio.Queue()
    req_q.put_nowait(("test_agent", Action(action_type=ActionType.JoinGame, params={}), {}))
    res_q = asyncio.Queue()

    cyst_wrapper = CYSTWrapper("env/netsecenv_conf.yaml", req_q, response_queue=res_q, cyst_objects=[])
    asyncio.run(cyst_wrapper.handle_incoming_action())
    req_q.put_nowait(("test_agent", Action(action_type=ActionType.ScanNetwork, params={"source_host":"192.168.0.4", "target_network":"192,168.0.1/24" }), {}))
   