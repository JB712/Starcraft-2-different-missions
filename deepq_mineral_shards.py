import numpy as np
import os
import dill
import tempfile
import tensorflow as tf
import zipfile

import baselines.common.tf_util as U

from baselines import logger
from baselines.common.schedules import LinearSchedule
from baselines import deepq
from baselines.deepq.replay_buffer import ReplayBuffer, PrioritizedReplayBuffer

from pysc2.lib import actions as sc2_actions
from pysc2.env import environment
from pysc2.lib import features
from pysc2.lib import actions

import absl.flags as flags
_PLAYER_RELATIVE = features.SCREEN_FEATURES.player_relative.index

_UNIT_TYPE = features.SCREEN_FEATURES.unit_type.index
_SELECTED = features.SCREEN_FEATURES.selected.index
_PLAYER_FRIENDLY = 1
_PLAYER_NEUTRAL = 3  # beacon/minerals
_PLAYER_HOSTILE = 4
_NO_OP = actions.FUNCTIONS.no_op.id
_SELECT_UNIT_ID = 1

_CONTROL_GROUP_SET = 1
_CONTROL_GROUP_RECALL = 0

_SELECT_CONTROL_GROUP = actions.FUNCTIONS.select_control_group.id
_MOVE_SCREEN = actions.FUNCTIONS.Move_screen.id
_ATTACK_SCREEN = actions.FUNCTIONS.Attack_screen.id
_SELECT_ARMY = actions.FUNCTIONS.select_army.id
_SELECT_UNIT = actions.FUNCTIONS.select_unit.id
_SELECT_POINT = actions.FUNCTIONS.select_point.id

_NOT_QUEUED = [0]
_SELECT_ALL = [0]

FLAGS = flags.FLAGS

class ActWrapper(object):
	def __init__(self, act):
		#global myVar
		#myVar = 0    
		self._act = act
		#self._act_params = act_params

	def update_group_list(obs):
		control_groups = obs[0].observation["control_groups"]
		group_count = 0
		group_list = []
		for id, group in enumerate(control_groups):
			if(group[0]!=0):
				group_count += 1
				group_list.append(id)
		return group_list

	@staticmethod
	def load(path, act_params, num_cpu=16):
		with open(path, "rb") as f:
			model_data = dill.load(f)
		act = deepq.build_act(**act_params)
		sess = U.make_session(num_cpu=num_cpu)
		sess.__enter__()
		with tempfile.TemporaryDirectory() as td:
			arc_path = os.path.join(td, "packed.zip")
			with open(arc_path, "wb") as f:
				f.write(model_data)

			zipfile.ZipFile(arc_path, 'r', zipfile.ZIP_DEFLATED).extractall(td)
			U.load_state(os.path.join(td, "model"))

		return ActWrapper(act)

	def __call__(self, *args, **kwargs):
		return self._act(*args, **kwargs)

	def save(self, path):
		"""Save model to a pickle located at `path`"""
		with tempfile.TemporaryDirectory() as td:
			U.save_state(os.path.join(td, "model"))
			arc_name = os.path.join(td, "packed.zip")
			with zipfile.ZipFile(arc_name, 'w') as zipf:
				for root, dirs, files in os.walk(td):
					for fname in files:
						file_path = os.path.join(root, fname)
						if file_path != arc_name:
							zipf.write(file_path, os.path.relpath(file_path, td))
			with open(arc_name, "rb") as f:
				model_data = f.read()
		with open(path, "wb") as f:
			dill.dump((model_data), f)


def load(path, act_params, num_cpu=16):
	"""Load act function that was returned by learn function.

	Parameters
	----------
	path: str
	    path to the act function pickle
	num_cpu: int
	    number of cpus to use for executing the policy

	Returns
	-------
	act: ActWrapper
	    function that takes a batch of observations
	    and returns actions.
	"""
	return ActWrapper.load(path, num_cpu=num_cpu, act_params=act_params)

"""def cb_locals(step):
  if step >= 100:
    return (True, step)

  return (False,)

def cb_globals(step):
  if step >= 100:
    return (True, step)

  return (False,)
"""

def learn(env,
          q_func,
          num_actions=3,
          lr=5e-4,
          max_timesteps=1000,
          buffer_size=50000,
          exploration_fraction=0.1,
          exploration_final_eps=0.02,
          train_freq=1,
          batch_size=32,
          print_freq=1,
          checkpoint_freq=10000,
          learning_starts=1000,
          gamma=1.0,
          target_network_update_freq=500,
          prioritized_replay=False,
          prioritized_replay_alpha=0.6,
          prioritized_replay_beta0=0.4,
          prioritized_replay_beta_iters=None,
          prioritized_replay_eps=1e-6,
          num_cpu=16,
          param_noise=False,
          param_noise_threshold=0.05,
          callback=None):
	"""Train a deepq model.

	Parameters
	-------
	env: pysc2.env.SC2Env
	    environment to train on
	q_func: (tf.Variable, int, str, bool) -> tf.Variable
	    the model that takes the following inputs:
	  observation_in: object
	            the output of observation placeholder
	num_actions: int
	            number of actions
	        scope: str
	        reuse: bool
	            should be passed to outer variable scope
	    and returns a tensor of shape (batch_size, num_actions) with values of every action.
	lr: float
	    learning rate for adam optimizer
	max_timesteps: int
	    number of env steps to optimizer for
	buffer_size: int
	    size of the replay buffer
	exploration_fraction: float
	    fraction of entire training period over which the exploration rate is annealed
	exploration_final_eps: float
	    final value of random action probability
	train_freq: int
	    update the model every `train_freq` steps.
	    set to None to disable printing
	batch_size: int
	    size of a batched sampled from replay buffer for training
	print_freq: int
	    how often to print out training progress
	    set to None to disable printing
	checkpoint_freq: int
	    how often to save the model. This is so that the best version is restored
	    at the end of the training. If you do not wish to restore the best version at
	    the end of the training set this variable to None.
	learning_starts: int
	    how many steps of the model to collect transitions for before learning starts
	gamma: float
	    discount factor
	target_network_update_freq: int
	    update the target network every `target_network_update_freq` steps.
	prioritized_replay: True
	    if True prioritized replay buffer will be used.
	prioritized_replay_alpha: float
	    alpha parameter for prioritized replay buffer
	prioritized_replay_beta0: float
	    initial value of beta for prioritized replay buffer
	prioritized_replay_beta_iters: int
	    number of iterations over which beta will be annealed from initial value
	    to 1.0. If set to None equals to max_timesteps.
	prioritized_replay_eps: float
	    epsilon to add to the TD errors when updating priorities.
	num_cpu: int
	    number of cpus to use for training
	callback: (locals, globals) -> None
	    function called at every steps with state of the algorithm.
	    If callback returns true training stops.

	Returns
	-------
	act: ActWrapper
	    Wrapper over act function. Adds ability to save it and load it.
	    See header of baselines/deepq/categorical.py for details on the act function.
	"""
	# Create all the functions necessary to train the model

	sess = U.make_session(num_cpu=num_cpu)
	sess.__enter__()

	def make_obs_ph(name):
		return U.BatchInput((64, 64), name=name)

	act, train, update_target, debug = deepq.build_train(
	        make_obs_ph=make_obs_ph,
	        q_func=q_func,
	        num_actions=num_actions,
	  optimizer=tf.train.AdamOptimizer(learning_rate=lr),
    gamma=gamma,
    grad_norm_clipping=10
	)
	act_params = {
	        'make_obs_ph': make_obs_ph,
	        'q_func': q_func,
	        'num_actions': num_actions,
	}

	# Create the replay buffer
	if prioritized_replay:
		replay_buffer = PrioritizedReplayBuffer(buffer_size, alpha=prioritized_replay_alpha)
		if prioritized_replay_beta_iters is None:
			prioritized_replay_beta_iters = max_timesteps
		beta_schedule = LinearSchedule(prioritized_replay_beta_iters,
		                               initial_p=prioritized_replay_beta0,
		                               final_p=1.0)
	else:
		replay_buffer = ReplayBuffer(buffer_size)
		beta_schedule = None
	# Create the schedule for exploration starting from 1.
	exploration = LinearSchedule(schedule_timesteps=int(exploration_fraction * max_timesteps),
	                             initial_p=1.0,
	                             final_p=exploration_final_eps)

	# Initialize the parameters and copy them to the target network.
	U.initialize()
	update_target()

	episode_rewards = [0.0]
	num_episodes = 0
	saved_mean_reward = None

	path_memory = np.zeros((64,64))

	obs = env.reset()

	# Select all marines first
	player_relative = obs[0].observation["screen"][_PLAYER_RELATIVE]

	screen = player_relative + path_memory

	player_y, player_x = (player_relative == _PLAYER_FRIENDLY).nonzero()
	obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_ARMY, [_SELECT_ALL])])

	for i in range(len(player_x)):
		xy = [player_x[i], player_y[i]]
		obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[0], xy])])

		group_id = 0
		group_list = []
		unit_xy_list = []
		for i in range(len(player_x)):
			if i % 4 != 0:
				continue

			if group_id > 2:
				break      

			xy = [player_x[i], player_y[i]]
			unit_xy_list.append(xy)

			if(len(unit_xy_list) >= 1):
				for idx, xy in enumerate(unit_xy_list):
					if(idx==0):
						obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[0], xy])])
					else:
						obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[1], xy])])

				obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_CONTROL_GROUP, [[_CONTROL_GROUP_SET], [group_id]])])
				unit_xy_list = []

				group_list.append(group_id)
				group_id += 1

		if(len(unit_xy_list) >= 1):
			for idx, xy in enumerate(unit_xy_list):
				if(idx==0):
					obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[0], xy])])
				else:
					obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[1], xy])])

			obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_CONTROL_GROUP, [[_CONTROL_GROUP_SET], [group_id]])])

			group_list.append(group_id)
			group_id += 1

			return obs    

	reset = True
	with tempfile.TemporaryDirectory() as td:
		model_saved = False
		model_file = os.path.join(td, "model")

		for t in range(max_timesteps):
			if t%1000 == 0:
				ActWrapper.save(ActWrapper, "mineral_shards.pkl")
			if callback is not None:
				if callback(locals(), globals()):
					break
			# Take action and update exploration to the newest value
			kwargs = {}
			if not param_noise:
				update_eps = exploration.value(t)
				update_param_noise_threshold = 0.
			else:
				update_eps = 0.
				if param_noise_threshold >= 0.:
					update_param_noise_threshold = param_noise_threshold
				else:
					# Compute the threshold such that the KL divergence between perturbed and non-perturbed
					# policy is comparable to eps-greedy exploration with eps = exploration.value(t).
					# See Appendix C.1 in Parameter Space Noise for Exploration, Plappert et al., 2017
					# for detailed explanation.
					update_param_noise_threshold = -np.log(1. - exploration.value(t) + exploration.value(t) / float(num_actions))
				kwargs['reset'] = reset
				kwargs['update_param_noise_threshold'] = update_param_noise_threshold
				kwargs['update_param_noise_scale'] = True
			action = act(np.array(screen)[None], update_eps=update_eps, **kwargs)[0]
			reset = False
			rew = 0

			#select marines
			player_relative = obs[0].observation["screen"][_PLAYER_RELATIVE]
			screen = player_relative + path_memory
			player = []

			while(len(group_list)>0):
				group_id = np.random.choice(group_list)
				obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_CONTROL_GROUP, [[_CONTROL_GROUP_RECALL], [group_id]])])

				selected = obs[0].observation["screen"][_SELECTED]
				player_y, player_x = (selected == _PLAYER_FRIENDLY).nonzero()
				if(len(player_y)>0):
					player = [int(player_x.mean()), int(player_y.mean())]
					break
				else:
					group_list.remove(group_id)

			if(len(player) == 2):

				if(player[0]>32):
					screen = shift(LEFT, player[0]-32, screen)
				elif(player[0]<32):
					screen = shift(RIGHT, 32 - player[0], screen)

				if(player[1]>32):
					screen = shift(UP, player[1]-32, screen)
				elif(player[1]<32):
					screen = shift(DOWN, 32 - player[1], screen)        


			coord = [player[0], player[1]]

			path_memory_ = np.array(path_memory, copy=True)

			if(action == 0): #UP

				if(player[1] >= 16):
					coord = [player[0], player[1] - 16]
					path_memory_[player[1] - 16 : player[1], player[0]] = -1
				elif(player[1] > 0):
					coord = [player[0], 0]
					path_memory_[0 : player[1], player[0]] = -1
						#else:
						#  rew -= 1

			elif(action == 1): #DOWN

				if(player[1] <= 47):
					coord = [player[0], player[1] + 16]
					path_memory_[player[1] : player[1] + 16, player[0]] = -1
				elif(player[1] > 47):
					coord = [player[0], 63]
					path_memory_[player[1] : 63, player[0]] = -1
						#else:
						#  rew -= 1

			elif(action == 2): #LEFT

				if(player[0] >= 16):
					coord = [player[0] - 16, player[1]]
					path_memory_[player[1], player[0] - 16 : player[0]] = -1
				elif(player[0] < 16):
					coord = [0, player[1]]
					path_memory_[player[1], 0 : player[0]] = -1
						#else:
						#  rew -= 1

			elif(action == 3): #RIGHT

				if(player[0] <= 47):
					coord = [player[0] + 16, player[1]]
					path_memory_[player[1], player[0] : player[0] + 16] = -1
				elif(player[0] > 47):
					coord = [63, player[1]]
					path_memory_[player[1], player[0] : 63] = -1      

			path_memory = np.array(path_memory_)

			if _MOVE_SCREEN not in obs[0].observation["available_actions"]:
				for i in range(len(player_x)):
					xy = [player_x[i], player_y[i]]
					obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[0], xy])])        
					#obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_ARMY, [_SELECT_ALL])])

			new_action = [sc2_actions.FunctionCall(_MOVE_SCREEN, [_NOT_QUEUED, coord])]

			# else:
			#   new_action = [sc2_actions.FunctionCall(_NO_OP, [])]

			obs = env.step(actions=new_action)

			player_relative = obs[0].observation["screen"][_PLAYER_RELATIVE]
			new_screen = player_relative + path_memory

			selected = obs[0].observation["screen"][_SELECTED]
			player_y, player_x = (selected == _PLAYER_FRIENDLY).nonzero()


			rew = obs[0].reward

			done = obs[0].step_type == environment.StepType.LAST

			# Store transition in the replay buffer.
			replay_buffer.add(screen, action, rew, new_screen, float(done))
			screen = new_screen

			episode_rewards[-1] += rew
			#episode_minerals[-1] += obs[0].reward

			if done:
				obs = env.reset()
				player_relative = obs[0].observation["screen"][_PLAYER_RELATIVE]

				screen = player_relative + path_memory

				player_y, player_x = (player_relative == _PLAYER_FRIENDLY).nonzero()
				player = [int(player_x.mean()), int(player_y.mean())]

				if(player[0]>32):
					screen = shift(LEFT, player[0]-32, screen)
				elif(player[0]<32):
					screen = shift(RIGHT, 32 - player[0], screen)

				if(player[1]>32):
					screen = shift(UP, player[1]-32, screen)
				elif(player[1]<32):
					screen = shift(DOWN, 32 - player[1], screen)        

				# Select all marines first
				obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_ARMY, [_SELECT_ALL])])

				for i in range(len(player_x)):
					xy = [player_x[i], player_y[i]]
					obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[0], xy])])

					group_id = 0
					group_list = []
					unit_xy_list = []
					for i in range(len(player_x)):
						if i % 4 != 0:
							continue

						if group_id > 2:
							break            

						xy = [player_x[i], player_y[i]]
						unit_xy_list.append(xy)

						if(len(unit_xy_list) >= 1):
							for idx, xy in enumerate(unit_xy_list):
								if(idx==0):
									obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[0], xy])])
								else:
									obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[1], xy])])

							obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_CONTROL_GROUP, [[_CONTROL_GROUP_SET], [group_id]])])
							unit_xy_list = []

							group_list.append(group_id)
							group_id += 1

					if(len(unit_xy_list) >= 1):
						for idx, xy in enumerate(unit_xy_list):
							if(idx==0):
								obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[0], xy])])
							else:
								obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_POINT, [[1], xy])])

						obs = env.step(actions=[sc2_actions.FunctionCall(_SELECT_CONTROL_GROUP, [[_CONTROL_GROUP_SET], [group_id]])])

						group_list.append(group_id)
						group_id += 1

					episode_rewards.append(0.0)
					reset = True

			if t > learning_starts and t % train_freq == 0:
				# Minimize the error in Bellman's equation on a batch sampled from replay buffer.
				if prioritized_replay:
					experience = replay_buffer.sample(batch_size, beta=beta_schedule.value(t))
					(obses_t, actions, rewards, obses_tp1, dones, weights, batch_idxes) = experience
				else:
					obses_t, actions, rewards, obses_tp1, dones = replay_buffer.sample(batch_size)
					weights, batch_idxes = np.ones_like(rewards), None
				td_errors = train(obses_t, actions, rewards, obses_tp1, dones, weights)
				if prioritized_replay:
					new_priorities = np.abs(td_errors) + prioritized_replay_eps
					replay_buffer.update_priorities(batch_idxes, new_priorities)

			if t > learning_starts and t % target_network_update_freq == 0:
				# Update target network periodically.
				update_target()

			mean_100ep_reward = round(np.mean(episode_rewards[-101:-1]), 1)
			#mean_100ep_mineral = round(np.mean(episode_minerals[-101:-1]), 1)
			num_episodes = len(episode_rewards)
			if done and print_freq is not None and len(episode_rewards) % print_freq == 0:
				logger.record_tabular("steps", t)
				logger.record_tabular("episodes", num_episodes )
				logger.record_tabular("mean 100 episode reward", mean_100ep_reward)
				#logger.record_tabular("mean 100 episode mineral", mean_100ep_mineral)
				logger.record_tabular("% time spent exploring", int(100 * exploration.value(t)))
				logger.dump_tabular()

			if (checkpoint_freq is not None and t > learning_starts and
			    num_episodes > 100 and t % checkpoint_freq == 0):
				if saved_mean_reward is None or mean_100ep_reward > saved_mean_reward:
					if print_freq is not None:
						logger.log("Saving model due to mean reward increase: {} -> {}".format(
						        saved_mean_reward, mean_100ep_reward))
					U.save_state(model_file)
					model_saved = True
					saved_mean_reward = mean_100ep_reward
		if model_saved:
			if print_freq is not None:
				logger.log("Restored model with mean reward: {}".format(saved_mean_reward))
			U.load_state(model_file)

	return ActWrapper(act)

def intToCoordinate(num, size=64):
	if size!=64:
		num = num * size * size // 4096
	y = num // size
	x = num - size * y
	return [x, y]

UP, DOWN, LEFT, RIGHT = 'up', 'down', 'left', 'right'

def shift(direction, number, matrix):
	''' shift given 2D matrix in-place the given number of rows or columns
	    in the specified (UP, DOWN, LEFT, RIGHT) direction and return it
	'''
	if direction in (UP):
		matrix = np.roll(matrix, -number, axis=0)
		matrix[number:,:] = -2
		return matrix
	elif direction in (DOWN):
		matrix = np.roll(matrix, number, axis=0)
		matrix[:number,:] = -2
		return matrix
	elif direction in (LEFT):
		matrix = np.roll(matrix, -number, axis=1)
		matrix[:,number:] = -2
		return matrix
	elif direction in (RIGHT):
		matrix = np.roll(matrix, number, axis=1)
		matrix[:,:number] = -2
		return matrix
	else:
		return matrix