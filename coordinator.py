#!/usr/bin/env python
# Server for the Aidojo project, coordinator
# Author: sebastian garcia, sebastian.garcia@agents.fel.cvut.cz
import argparse
from datetime import datetime
import logging
import json
import asyncio
from env.network_security_game import NetworkSecurityEnvironment
from env.game_components import Action, Observation, ActionType, GameStatus
from utils.utils import observation_to_str
from pathlib import Path
import os
import time


# Set the logging
log_filename=Path('coordinator.log')
if not log_filename.parent.exists():
    os.makedirs(log_filename.parent)
logging.basicConfig(filename=log_filename, filemode='w', format='%(asctime)s %(name)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S',level=logging.INFO)
logger = logging.getLogger('Coordinator')

class ActionProcessor:

    def __init__(self, logger) -> None:
        self._logger = logging.getLogger('Coordinator-ActionProcessor')
        self._observations = {}
        self._logger.info("Action Processor created")
    
    def process_message_from_agent(self, agent_id:int, action:Action)->Action:
        """
        Method for processing message coming from the agent for the game engine.
        input str JSON
        output Action
        """
        self._logger.debug(f"Processing message from agent {agent_id}: {Action}")
        a =  action
        return a
               
    
    def generate_observation_msg_for_agent(self, agent_id:int, new_observation:Observation)->str:
        """
        Method for processing a NetSecGame gamestate into an partial observation for an agent

        Action.from
        """
        self._logger.debug(f"Processing message to agent {agent_id}: {new_observation}")
        self._observations[agent_id] = new_observation
        msg_for_agent = observation_to_str(new_observation)
        return msg_for_agent



# Get a new world
myworld = NetworkSecurityEnvironment('env/netsecenv_conf.yaml')

action_processor = ActionProcessor(logger)

__version__ = 'v0.2'

async def start_tasks():
    """
    High level funciton to start all the other asynchronous tasks and queues
    - Reads the conf of the coordinator
    - Creates queues 
    - Start the main part of the coordinator
    - Start a server that listens for agents
    """
    logger.info('Starting all tasks')

    # Read the configuration
    logger.info('Read configuration of coordinator.')
    with open(args.configfile, 'r') as jfile:
        confjson = json.load(jfile)
    host = confjson.get('host', None)
    port = confjson.get('port', None)

    # Create two asyncio queues
    actions_queue = asyncio.Queue()
    answers_queue = asyncio.Queue()

    logger.info('Starting the server listening for agents')
    # start_server returns a coroutine, so 'await' runs this coroutine
    server = await asyncio.start_server(lambda r, w: handle_new_agent(r, w, actions_queue, answers_queue), host, port)

    logger.info('Starting main coordinator tasks')
    asyncio.create_task(main_coordinator(actions_queue, answers_queue))

    addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    logger.info(f'\tServing on {addrs}')

    try:
        async with server:
            # The server will keep running concurrently due to serve_forever
            await server.serve_forever()
            # When you call await server.serve_forever(), it doesn't block the execution of the program. Instead, it starts an event loop that keeps running in the background, accepting and handling connections as they come in. The await keyword allows the event loop to run other asynchronous tasks while waiting for events like incoming connections.
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        await server.wait_closed()
 
async def main_coordinator(actions_queue, answers_queue, ALLOWED_ROLES=['Attacker', 'Defender', 'Human']):
    """
    The main coordinator is in charge of everything exept the coomuncation with agents
    Work includes:
    - Accesing the queue of actions
    - Checking the actions done
    - Contacting the environment
    - Accesing the queue of answers
    - With the agents, offer to register, put a nick, select a side, and start playing, wait for others or see status
    """
    try:
        logger.info("Main coordinator started.")
        global myworld
        env_observation = myworld.reset()
        agents = {}

        while True:
            logger.debug("Coordinator running.")
            # Read message from the queue
            agent_addr, message = await actions_queue.get()
            if message is not None:
                logger.info(f"Coordinator received: {message}.")
                try:  # Convert message to Action
                    action = Action.from_json(message)
                except Exception as e:
                    logger.error(f"Error when converting msg to Action using Action.from_json():{e}")
                match action.type:
                    case ActionType.JoinGame:
                        if agent_addr not in agents:
                            logger.info(f"Creating new agent for {agent_addr}.")
                            agent_name = action.parameters["agent_info"].name
                            agent_role = action.parameters["agent_info"].role
                            if agent_role in  ALLOWED_ROLES:
                                logger.info(f"\tAgent {agent_name}, registred as {agent_role}")
                                agents[agent_addr] = action.parameters
                                agent_observation_str = action_processor.generate_observation_msg_for_agent(agent_addr, env_observation)
                                output_message_dict = {"to_agent": agent_addr, "status": str(GameStatus.CREATED), "observation": agent_observation_str, "message": f"Welcome {agent_name}, registred as {agent_role}"}
                            else:
                                logger.info(f"\tError in regitration, unknown agent role: {agent_role}!")
                                output_message_dict = {"to_agent": agent_addr, "status": str(GameStatus.BAD_REQUEST), "message": f"Incorrect agent_role {agent_role}"}
                        else:
                            logger.info(f"\tError in regitration, unknown agent already exists!")
                            output_message_dict = {"to_agent": {agent_addr}, "status": str(GameStatus.BAD_REQUEST), "message": "Agent already exists."}
                    case ActionType.QuitGame:
                        raise NotImplementedError
                    case ActionType.ResetGame:
                        logger.info(f"Coordinator received from RESET request from agent {agent_addr}")
                        new_env_observation = myworld.reset()
                        agent_observation_str = action_processor.generate_observation_msg_for_agent(agent_addr, new_env_observation)
                        output_message_dict = {"to_agent": agent_addr, "status": str(GameStatus.OK), "observation": agent_observation_str, "message": "Resetting Game and starting again."}
                    case _:
                        # Process ALL other ActionTypes
                        # Access agent information
                        logger.info(f'Coordinator received from agent {agent_addr}: {action}')
                        # Process the message
                        action_for_env = action_processor.process_message_from_agent(agent_addr, action)
                        new_observation = myworld.step(action_for_env)
                        agent_observation_str = action_processor.generate_observation_msg_for_agent(agent_addr,new_observation)
                        # send the action to the env and get new gamestate
                        # Answer the agents
                        output_message_dict = {"agent": agent_addr, "observation": agent_observation_str, "status": str(GameStatus.OK)}
                try:
                    # Convert message into string representation
                    output_message = json.dumps(output_message_dict)
                except Exception as e:
                    logger.error(f"Error when converting msg to Json:{e}")
                    raise e
                # Send to anwer_queue
                await answers_queue.put(output_message)
            await asyncio.sleep(0.01)
    except KeyboardInterrupt:
        logger.debug('Terminating by KeyboardInterrupt')
        raise SystemExit
    except Exception as e:
        logger.error(f'Exception in main_coordinator(): {e}')
        raise e

async def handle_new_agent(reader, writer, actions_queue, answers_queue):
    """
    Function to deal with each new agent
    """
    try:
        addr = writer.get_extra_info('peername')
        logger.info(f"New agent connected: {addr}")
        while True:
            data = await reader.read(500)
            raw_message = data.decode().strip()
            if len(raw_message):
                logger.info(f"Handler received from {addr}: {raw_message!r}, len={len(raw_message)}")

                # Put the message and agent information into the queue
                await actions_queue.put((addr, raw_message))

                # Read messages from the queue and send to the agent
                message = await answers_queue.get()
                if message:
                    logger.info(f"Handle sending to agent {addr}: {message!r}")
                    await send_data_to_agent(writer, message)
                    try:
                        await writer.drain()
                    except ConnectionResetError:
                        logger.info(f'Connection lost. Agent disconnected.')
            else:
                logger.info(f"Handler received from {addr}: {raw_message!r}, len={len(raw_message)}")
                logger.info(f"\tEmpty message, terminating agent on address {addr}")
                break
    except KeyboardInterrupt:
        logger.debug('Terminating by KeyboardInterrupt')
        raise SystemExit
    except Exception as e:
        logger.error(f'Exception in handle_new_agent(): {e}')

async def send_data_to_agent(writer, data:str)->None:
    """
    Send the world to the agent
    """
    writer.write(bytes(str(data).encode()))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser = argparse.ArgumentParser(description=f"NetSecGame Coordinator Server version {__version__}. Author: Sebastian Garcia, sebastian.garcia@agents.fel.cvut.cz", usage='%(prog)s [options]')
    parser.add_argument('-v', '--verbose', help='Verbosity level. This shows more info about the results.', action='store', required=False, type=int)
    parser.add_argument('-d', '--debug', help='Debugging level. This shows inner information about the flows.', action='store', required=False, type=int)
    parser.add_argument('-c', '--configfile', help='Configuration file.', action='store', required=False, type=str, default='coordinator.conf')

    args = parser.parse_args()
    # Get the event loop and run it
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_tasks())
    except KeyboardInterrupt:
        logger.debug('Terminating by KeyboardInterrupt')
        raise SystemExit
    except Exception as e:
        logger.error(f'Exception in __main__: {e}')
    finally:
        loop.close()