# -*- coding: utf-8 -*-

from cmath import log
from fedscale.core import response
from fedscale.core.fl_aggregator_libs import *
from fedscale.core.resource_manager import ResourceManager
from fedscale.core import events
from fedscale.core import job_api_pb2
import fedscale.core.job_api_pb2_grpc as job_api_pb2_grpc

import torch
from torch.utils.tensorboard import SummaryWriter
import threading
import pickle
import grpc
from concurrent import futures

MAX_MESSAGE_LENGTH = 1*1024*1024*1024 # 1GB

class Aggregator(job_api_pb2_grpc.JobServiceServicer):
    """This centralized aggregator collects training/testing feedbacks from executors"""
    def __init__(self, args):
        logging.info(f"Job args {args}")

        self.args = args
        self.experiment_mode = args.experiment_mode
        self.device = args.cuda_device if args.use_cuda else torch.device('cpu')

        # ======== env information ========
        self.this_rank = 0
        self.global_virtual_clock = 0.
        self.round_duration = 0.
        self.resource_manager = ResourceManager(self.experiment_mode)
        self.client_manager = self.init_client_manager(args=args)

        # ======== model and data ========
        self.model = None
        self.model_in_update = 0
        self.update_lock = threading.Lock()
        self.last_global_model = []
        self.model_state_dict = None

        # ======== channels ========
        self.connection_timeout = self.args.connection_timeout
        self.executors = None
        self.grpc_server = None

        # ======== Event Queue =======
        self.individual_client_events = {}    # Unicast 
        self.sever_events_queue = collections.deque()
        self.broadcast_events_queue = collections.deque() # Broadcast

        # ======== runtime information ========
        self.tasks_round = 0
        # NOTE: sampled_participants = sampled_executors in deployment, 
        # because every participant is an executor. However, in simulation mode,
        # executors is the physical machines (VMs), thus: 
        # |sampled_executors| << |sampled_participants| as an VM may run multiple participants
        self.sampled_participants = []
        self.sampled_executors = []

        self.round_stragglers = []
        self.model_update_size = 0.

        self.collate_fn = None
        self.task = args.task
        self.round = 0

        self.start_run_time = time.time()
        self.client_conf = {}

        self.stats_util_accumulator = []
        self.loss_accumulator = []
        self.client_training_results = []

        # number of registered executors
        self.registered_executor_info = set()
        self.test_result_accumulator = []
        self.testing_history = {'data_set': args.data_set, 'model': args.model, 'sample_mode': args.sample_mode,
                        'gradient_policy': args.gradient_policy, 'task': args.task, 'perf': collections.OrderedDict()}

        self.log_writer = SummaryWriter(log_dir=logDir)

        # ======== Task specific ============
        self.imdb = None           # object detection


    def setup_env(self):
        self.setup_seed(seed=self.this_rank)

        # set up device
        if self.args.use_cuda and self.device == None:
            for i in range(torch.cuda.device_count()):
                try:
                    self.device = torch.device('cuda:'+str(i))
                    torch.cuda.set_device(i)
                    _ = torch.rand(1).to(device=self.device)
                    logging.info(f'End up with cuda device ({self.device})')
                    break
                except Exception as e:
                    assert i != torch.cuda.device_count()-1, 'Can not find available GPUs'
        self.optimizer = ServerOptimizer(self.args.gradient_policy, self.args, self.device)


    def setup_seed(self, seed=1):
        """Set global random seed for better reproducibility"""
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        np.random.seed(seed)
        random.seed(seed)
        torch.backends.cudnn.deterministic = True


    def init_control_communication(self):
        # Create communication channel between aggregator and worker
        # This channel serves control messages
        logging.info(f"Initiating control plane communication ...")
        if self.experiment_mode == events.SIMULATION_MODE:
            num_of_executors = 0
            for ip_numgpu in self.args.executor_configs.split("="):
                ip, numgpu = ip_numgpu.split(':')
                for numexe in numgpu.strip()[1:-1].split(','):
                    for _ in range(int(numexe.strip())):
                        num_of_executors += 1
            self.executors = list(range(num_of_executors))
        else:
            self.executors = []

        # initiate a server process
        self.grpc_server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=20),
            options=[
                ('grpc.max_send_message_length', MAX_MESSAGE_LENGTH),
                ('grpc.max_receive_message_length', MAX_MESSAGE_LENGTH),
            ],
        )
        job_api_pb2_grpc.add_JobServiceServicer_to_server(self, self.grpc_server)
        port = '[::]:{}'.format(self.args.ps_port)

        logging.info(f'%%%%%%%%%% Opening aggregator sever using port {port} %%%%%%%%%%')

        self.grpc_server.add_insecure_port(port)
        self.grpc_server.start()


    def init_data_communication(self):
        """For jumbo traffics (e.g., training results).
        """
        pass

    def init_model(self):
        """Load model"""
        if self.args.task == "detection":
            cfg_from_file(self.args.cfg_file)
            np.random.seed(self.cfg.RNG_SEED)
            self.imdb, _, _, _ = combined_roidb("voc_2007_test", ['DATA_DIR', self.args.data_dir], server=True)

        return init_model()

    def init_client_manager(self, args):
        """
            Currently we implement two client managers:
            1. Random client sampler
                - it selects participants randomly in each round
                - [Ref]: https://arxiv.org/abs/1902.01046
            2. Oort sampler
                - Oort prioritizes the use of those clients who have both data that offers the greatest utility
                  in improving model accuracy and the capability to run training quickly.
                - [Ref]: https://www.usenix.org/conference/osdi21/presentation/lai
        """

        # sample_mode: random or kuiper
        client_manager = clientManager(args.sample_mode, args=args)

        return client_manager

    def load_client_profile(self, file_path):
        """For Simulation Mode: load client profiles/traces"""
        global_client_profile = {}
        if os.path.exists(file_path):
            with open(file_path, 'rb') as fin:
                # {clientId: [computer, bandwidth]}
                global_client_profile = pickle.load(fin)

        return global_client_profile

    def executor_info_handler(self, executorId, info):

        self.registered_executor_info.add(executorId)
        logging.info(f"Received executor {executorId} information, {len(self.registered_executor_info)}/{len(self.executors)}")
        # have collected all executors
        # In this simulation, we run data split on each worker, so collecting info from one executor is enough
        # Waiting for data information from executors, or timeout

        if len(self.registered_executor_info) == len(self.executors):

            clientId = 1
            logging.info(f"Loading {len(info['size'])} client traces ...")
            for _size in info['size']:
                # since the worker rankId starts from 1, we also configure the initial dataId as 1
                mapped_id = clientId%len(self.client_profiles) if len(self.client_profiles) > 0 else 1
                systemProfile = self.client_profiles.get(mapped_id, {'computation': 1.0, 'communication':1.0})
                self.client_manager.registerClient(executorId, clientId, size=_size, speed=systemProfile)
                self.client_manager.registerDuration(clientId, batch_size=self.args.batch_size,
                    upload_step=self.args.local_steps, upload_size=self.model_update_size, download_size=self.model_update_size)
                clientId += 1

            logging.info("Info of all feasible clients {}".format(self.client_manager.getDataInfo()))

            # start to sample clients
            self.round_completion_handler()


    def tictak_client_tasks(self, sampled_clients, num_clients_to_collect):
        if self.experiment_mode == events.SIMULATION_MODE:
            # NOTE: We try to remove dummy events as much as possible in simulations, 
            # by removing the stragglers/offline clients in overcommitment"""
            sampledClientsReal = []
            completionTimes = []
            completed_client_clock = {}
            # 1. remove dummy clients that are not available to the end of training
            for client_to_run in sampled_clients:
                client_cfg = self.client_conf.get(client_to_run, self.args)

                exe_cost = self.client_manager.getCompletionTime(client_to_run,
                                        batch_size=client_cfg.batch_size, upload_step=client_cfg.local_steps,
                                        upload_size=self.model_update_size, download_size=self.model_update_size)

                roundDuration = exe_cost['computation'] + exe_cost['communication']
                # if the client is not active by the time of collection, we consider it is lost in this round
                if self.client_manager.isClientActive(client_to_run, roundDuration + self.global_virtual_clock):
                    sampledClientsReal.append(client_to_run)
                    completionTimes.append(roundDuration)
                    completed_client_clock[client_to_run] = exe_cost

            num_clients_to_collect = min(num_clients_to_collect, len(completionTimes))
            # 2. get the top-k completions to remove stragglers
            sortedWorkersByCompletion = sorted(range(len(completionTimes)), key=lambda k:completionTimes[k])
            top_k_index = sortedWorkersByCompletion[:num_clients_to_collect]
            clients_to_run = [sampledClientsReal[k] for k in top_k_index]

            dummy_clients = [sampledClientsReal[k] for k in sortedWorkersByCompletion[num_clients_to_collect:]]
            round_duration = completionTimes[top_k_index[-1]]
            completionTimes.sort()

            return clients_to_run, dummy_clients, completed_client_clock, round_duration, completionTimes[:num_clients_to_collect]
        else:
            completed_client_clock = {client:1 for client in sampled_clients}
            return sampled_clients, sampled_clients, completed_client_clock, 1, list(completed_client_clock.values())

    def run(self):
        self.setup_env()
        self.model = self.init_model()
        self.save_last_param()
        self.model_update_size = sys.getsizeof(pickle.dumps(self.model))/1024.0*8. # kbits
        self.client_profiles = self.load_client_profile(file_path=self.args.device_conf_file)

        self.init_control_communication()
        self.init_data_communication()
        self.event_monitor()


    def select_participants(self, select_num_participants, overcommitment=1.3):
        return sorted(self.client_manager.resampleClients(
            int(select_num_participants*overcommitment), cur_time=self.global_virtual_clock))


    def client_completion_handler(self, results):
        """We may need to keep all updates from clients, if so, we need to append results to the cache"""
        # Format:
        #       -results = {'clientId':clientId, 'update_weight': model_param, 'moving_loss': round_train_loss,
        #       'trained_size': count, 'wall_duration': time_cost, 'success': is_success 'utility': utility}

        if self.args.gradient_policy in ['q-fedavg']:
            self.client_training_results.append(results)

        # Feed metrics to client sampler
        self.stats_util_accumulator.append(results['utility'])
        self.loss_accumulator.append(results['moving_loss'])

        self.client_manager.registerScore(results['clientId'], results['utility'], 
            auxi=math.sqrt(results['moving_loss']),
            time_stamp=self.round,
            duration=self.virtual_client_clock[results['clientId']]['computation']+
                self.virtual_client_clock[results['clientId']]['communication']
        )

        device = self.device
        """
            [FedAvg] "Communication-Efficient Learning of Deep Networks from Decentralized Data".
            H. Brendan McMahan, Eider Moore, Daniel Ramage, Seth Hampson, Blaise Aguera y Arcas. AISTATS, 2017
        """
        # Start to take the average of updates, and we do not keep updates to save memory
        # Importance of each update is 1/#_of_participants
        # importance = 1./self.tasks_round

        self.update_lock.acquire()
        # ================== Aggregate weights ======================

        self.model_in_update += 1

        if self.model_in_update == 1:
            self.model_state_dict = self.model.state_dict()
            for idx, param in enumerate(self.model_state_dict.values()):
                param.data = (torch.from_numpy(results['update_weight'][idx]).to(device=device))
        else:
            for idx, param in enumerate(self.model_state_dict.values()):
                param.data += (torch.from_numpy(results['update_weight'][idx]).to(device=device))

        if self.model_in_update == self.tasks_round:
            for idx, param in enumerate(self.model_state_dict.values()):
                param.data = (param.data/float(self.tasks_round)).to(dtype=param.data.dtype)

            self.model.load_state_dict(self.model_state_dict)

        self.update_lock.release()

    def save_last_param(self):
        self.last_global_model = [param.data.clone() for param in self.model.parameters()]


    def round_weight_handler(self, last_model, current_model):
        if self.round > 1:
            self.optimizer.update_round_gradient(last_model, current_model, self.model)


    def round_completion_handler(self):
        self.global_virtual_clock += self.round_duration
        self.round += 1

        if self.round % self.args.decay_round == 0:
            self.args.learning_rate = max(self.args.learning_rate*self.args.decay_factor, self.args.min_learning_rate)

        # handle the global update w/ current and last
        self.round_weight_handler(self.last_global_model, [param.data.clone() for param in self.model.parameters()])

        avgUtilLastround = sum(self.stats_util_accumulator)/max(1, len(self.stats_util_accumulator))
        # assign avg reward to explored, but not ran workers
        for clientId in self.round_stragglers:
            self.client_manager.registerScore(clientId, avgUtilLastround,
                    time_stamp=self.round,
                    duration=self.virtual_client_clock[clientId]['computation']+self.virtual_client_clock[clientId]['communication'],
                    success=False)

        avg_loss = sum(self.loss_accumulator)/max(1, len(self.loss_accumulator))
        logging.info(f"Wall clock: {round(self.global_virtual_clock)} s, round: {self.round}, Planned participants: " + \
            f"{len(self.sampled_participants)}, Succeed participants: {len(self.stats_util_accumulator)}, Training loss: {avg_loss}")

        # dump round completion information to tensorboard
        if len(self.loss_accumulator):
            self.log_train_result(avg_loss)

        # update select participants
        self.sampled_participants = self.select_participants(
                        select_num_participants=self.args.total_worker, overcommitment=self.args.overcommitment)
        clientsToRun, round_stragglers, virtual_client_clock, round_duration, flatten_client_duration = self.tictak_client_tasks(
                        self.sampled_participants, self.args.total_worker)

        logging.info(f"Selected participants to run: {clientsToRun}")

        # Issue requests to the resource manager; Tasks ordered by the completion time
        self.resource_manager.register_tasks(clientsToRun)
        self.tasks_round = len(clientsToRun)

        # Update executors and participants
        if self.experiment_mode == events.SIMULATION_MODE:
            self.sampled_executors = list(self.individual_client_events.keys())
        else:
            self.sampled_executors = [str(c_id) for c_id in self.sampled_participants]

        self.save_last_param()
        self.round_stragglers = round_stragglers
        self.virtual_client_clock = virtual_client_clock
        self.flatten_client_duration = numpy.array(flatten_client_duration)
        self.round_duration = round_duration
        self.model_in_update = 0
        self.test_result_accumulator = []
        self.stats_util_accumulator = []
        self.client_training_results = []

        if self.round >= self.args.rounds:
            self.broadcast_aggregator_events(events.SHUT_DOWN)
        elif self.round % self.args.eval_interval == 0:
            self.broadcast_aggregator_events(events.UPDATE_MODEL)
            self.broadcast_aggregator_events(events.MODEL_TEST)
        else:
            self.broadcast_aggregator_events(events.UPDATE_MODEL)
            self.broadcast_aggregator_events(events.START_ROUND)

    def log_train_result(self, avg_loss):
        """Result will be post on TensorBoard"""
        self.log_writer.add_scalar('Train/round_to_loss', avg_loss, self.round)
        self.log_writer.add_scalar('FAR/time_to_train_loss (min)', avg_loss, self.global_virtual_clock/60.)
        self.log_writer.add_scalar('FAR/round_duration (min)', self.round_duration/60., self.round)
        self.log_writer.add_histogram('FAR/client_duration (min)', self.flatten_client_duration, self.round)

    def log_test_result(self):
        self.log_writer.add_scalar('Test/round_to_loss', self.testing_history['perf'][self.round]['loss'], self.round)
        self.log_writer.add_scalar('Test/round_to_accuracy', self.testing_history['perf'][self.round]['top_1'], self.round)
        self.log_writer.add_scalar('FAR/time_to_test_loss (min)', self.testing_history['perf'][self.round]['loss'],
                                    self.global_virtual_clock/60.)
        self.log_writer.add_scalar('FAR/time_to_test_accuracy (min)', self.testing_history['perf'][self.round]['top_1'],
                                    self.global_virtual_clock/60.)


    def deserialize_response(self, responses):
        return pickle.loads(responses)

    def serialize_response(self, responses):
        return pickle.dumps(responses)

    def testing_completion_handler(self, client_id, results):
        """Each executor will handle a subset of testing dataset"""

        results = results['results']

        # List append is thread-safe
        self.test_result_accumulator.append(results)

        # Have collected all testing results
        if len(self.test_result_accumulator) == len(self.executors):
            accumulator = self.test_result_accumulator[0]
            for i in range(1, len(self.test_result_accumulator)):
                if self.args.task == "detection":
                    for key in accumulator:
                        if key == "boxes":
                            for j in range(self.imdb.num_classes):
                                accumulator[key][j] = accumulator[key][j] + self.test_result_accumulator[i][key][j]
                        else:
                            accumulator[key] += self.test_result_accumulator[i][key]
                else:
                    for key in accumulator:
                        accumulator[key] += self.test_result_accumulator[i][key]
            if self.args.task == "detection":
                self.testing_history['perf'][self.round] = {'round': self.round, 'clock': self.global_virtual_clock,
                    'top_1': round(accumulator['top_1']*100.0/len(self.test_result_accumulator), 4),
                    'top_5': round(accumulator['top_5']*100.0/len(self.test_result_accumulator), 4),
                    'loss': accumulator['test_loss'],
                    'test_len': accumulator['test_len']
                }
            else:
                self.testing_history['perf'][self.round] = {'round': self.round, 'clock': self.global_virtual_clock,
                    'top_1': round(accumulator['top_1']/accumulator['test_len']*100.0, 4),
                    'top_5': round(accumulator['top_5']/accumulator['test_len']*100.0, 4),
                    'loss': accumulator['test_loss']/accumulator['test_len'],
                    'test_len': accumulator['test_len']
                }


            logging.info("FL Testing in round: {}, virtual_clock: {}, top_1: {} %, top_5: {} %, test loss: {:.4f}, test len: {}"
                    .format(self.round, self.global_virtual_clock, self.testing_history['perf'][self.round]['top_1'],
                    self.testing_history['perf'][self.round]['top_5'], self.testing_history['perf'][self.round]['loss'],
                    self.testing_history['perf'][self.round]['test_len']))

            # Dump the testing result
            with open(os.path.join(logDir, 'testing_perf'), 'wb') as fout:
                pickle.dump(self.testing_history, fout)

            if len(self.loss_accumulator):
                self.log_test_result()

            self.broadcast_events_queue.append(events.START_ROUND)


    def broadcast_aggregator_events(self, event):
        """Issue tasks (events) to aggregator worker processes"""
        self.broadcast_events_queue.append(event)

    def dispatch_client_events(self, event, clients=None):
        """Issue tasks (events) to clients"""
        if clients is None:
            clients = self.sampled_executors

        for client_id in clients:
            self.individual_client_events[client_id].append(event)

    def get_client_conf(self, clientId):
        """Training configurations that will be applied on clients"""

        conf = {
            'learning_rate': self.args.learning_rate,
            'model': None # none indicates we are using the global model
        }
        return conf

    def create_client_task(self, executorId):
        """Issue a new client training task to the executor"""

        next_clientId = self.resource_manager.get_next_task()
        train_config = None
        # NOTE: model = None then the executor will load the global model broadcasted in UPDATE_MODEL
        model = None 
        if next_clientId != None:
            config = self.get_client_conf(next_clientId)
            train_config = {'client_id': next_clientId, 'task_config': config}
        return train_config, model

    
    def get_test_config(self, client_id):
        """FL model testing on clients"""

        return {'client_id':client_id}

    def get_global_model(self):
        """Get global model that would be used by all FL clients (in default FL)"""
        return self.model
    
    def get_shutdown_config(self, client_id):
        return {'client_id': client_id}

    def add_event_handler(self, client_id, event, meta, data):
        """ Due to the large volume of requests, we will put all events into a queue first."""
        self.sever_events_queue.append((client_id, event, meta, data))


    def CLIENT_REGISTER(self, request, context):
        """FL Client register to the aggregator"""

        # NOTE: client_id = executor_id in deployment, 
        # while multiple client_id uses the same executor_id (VMs) in simulations
        executor_id = request.executor_id
        executor_info = self.deserialize_response(request.executor_info)
        if executor_id not in self.individual_client_events:
            logging.info(f"Detect new client: {executor_id}, executor info: {executor_info}")
            self.individual_client_events[executor_id] = collections.deque()
        else:
            logging.info(f"Previous client: {executor_id} resumes connecting")

        # We can customize whether to admit the clients here
        self.executor_info_handler(executor_id, executor_info)
        
        return job_api_pb2.ServerResponse(event=events.DUMMY_EVENT,
                meta=None, data=None)


    def CLIENT_PING(self, request, context):
        """Handle client requests"""

        # NOTE: client_id = executor_id in deployment, 
        # while multiple client_id may use the same executor_id (VMs) in simulations
        executor_id, client_id = request.executor_id, request.client_id
        response_data = response_msg = None

        if len(self.individual_client_events[executor_id]) == 0:
            # send dummy response
            current_event = events.DUMMY_EVENT
            response_data = response_msg = events.DUMMY_RESPONSE
        else:
            current_event = self.individual_client_events[executor_id].popleft()
            if current_event == events.CLIENT_TRAIN:
                response_msg, response_data = self.create_client_task(client_id)
                if response_msg is None:
                    current_event = events.DUMMY_EVENT
            elif current_event == events.MODEL_TEST:
                response_msg = self.get_test_config(client_id)
            elif current_event == events.UPDATE_MODEL:
                response_data = self.get_global_model()
            elif current_event == events.SHUT_DOWN:
                response_msg = self.get_shutdown_config(executor_id)

        response_msg, response_data = self.serialize_response(response_msg), self.serialize_response(response_data)
        # NOTE: in simulation mode, response data is pickle for faster (de)serialization
        return job_api_pb2.ServerResponse(event=current_event,
                meta=response_msg, data=response_data)


    def CLIENT_EXECUTE_COMPLETION(self, request, context):
        """FL clients complete the execution task."""

        executor_id, client_id, event = request.executor_id, request.client_id, request.event
        execution_status, execution_msg = request.status, request.msg
        meta_result, data_result = request.meta_result, request.data_result

        if event == events.CLIENT_TRAIN:
            # Training results may be uploaded in CLIENT_EXECUTE_RESULT request later, 
            # so we need to specify whether to ask client to do so (in case of straggler/timeout in real FL).
            if execution_status is False:
                logging.error(f"Executor {executor_id} fails to run client {client_id}, due to {execution_msg}")
            if self.resource_manager.has_next_task(executor_id):
                # NOTE: we do not pop the train immediately in simulation mode,
                # since the executor may run multiple clients
                self.individual_client_events[executor_id].appendleft(events.CLIENT_TRAIN)

        elif event in (events.MODEL_TEST, events.UPLOAD_MODEL):
            self.add_event_handler(executor_id, event, meta_result, data_result)
        else:
            logging.error(f"Received undefined event {event} from client {client_id}")
        return self.CLIENT_PING(request, context)


    def event_monitor(self):
        logging.info("Start monitoring events ...")

        while True:
            # Broadcast events to clients
            if len(self.broadcast_events_queue) > 0:
                current_event = self.broadcast_events_queue.popleft()

                if current_event in (events.UPDATE_MODEL, events.MODEL_TEST):
                    self.dispatch_client_events(current_event)

                elif current_event == events.START_ROUND:
                    self.dispatch_client_events(events.CLIENT_TRAIN)
                
                elif current_event == events.SHUT_DOWN:
                    self.dispatch_client_events(events.SHUT_DOWN)
                    break

            # Handle events queued on the aggregator
            elif len(self.sever_events_queue) > 0:
                client_id, current_event, meta, data = self.sever_events_queue.popleft()

                if current_event == events.UPLOAD_MODEL:
                    self.client_completion_handler(self.deserialize_response(data))
                    if len(self.stats_util_accumulator) == self.tasks_round:
                            self.round_completion_handler()

                elif current_event == events.MODEL_TEST:
                    self.testing_completion_handler(client_id, self.deserialize_response(data))

                else:
                    logging.error(f"Event {current_event} is not defined")
                
            else:
                # execute every 100 ms
                time.sleep(0.1)


    def stop(self):
        logging.info(f"Terminating the aggregator ...")
        time.sleep(5)

if __name__ == "__main__":
    aggregator = Aggregator(args)
    aggregator.run()
