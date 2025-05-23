from fedscale.core import events
import threading

class ResourceManager(object):
    """Schedule training tasks across GPUs/CPUs"""

    def __init__(self, experiment_mode):

        self.client_run_queue = []
        self.client_run_queue_idx = 0
        self.experiment_mode = experiment_mode
        self.update_lock = threading.Lock()
    
    def register_tasks(self, clientsToRun):
        self.client_run_queue = clientsToRun.copy()
        self.client_run_queue_idx = 0

    def remove_client_task(self, client_id):
        assert(client_id in self.client_run_queue, 
            f"client task {client_id} is not in task queue")
        pass

    def has_next_task(self, client_id=None):
        exist_next_task = False
        if self.experiment_mode == events.SIMULATION_MODE:
            exist_next_task = self.client_run_queue_idx < len(self.client_run_queue)
        else:
            exist_next_task = client_id in self.client_run_queue
        return exist_next_task

    def get_next_task(self, client_id=None):
        next_task_id = None
        self.update_lock.acquire()
        if self.experiment_mode == events.SIMULATION_MODE:
            if self.has_next_task(client_id):
                next_task_id = self.client_run_queue[self.client_run_queue_idx]
                self.client_run_queue_idx += 1
        else:
            if client_id in self.client_run_queue:
                next_task_id = client_id
                self.client_run_queue.remove(next_task_id)

        self.update_lock.release()
        return next_task_id
