
## FedScale Runtime: A Deployment and Evaluation Platform for Federated Learning

FedScale Runtime is an scalable and extensible deployment and evaluation platform. 
It simplifies and standardizes the deployment and experimental setups and enables model evaluation under practical settings through user-friendly APIs.
It evolved from our prior system, Oort [Oort project](https://github.com/SymbioticLab/Oort), which has been shown to scale well and can emulate FL training of thousands of clients in each round.

## Architecture

<img src="faroverview.png" alt="FAR enables the developer to benchmark various FL efforts with practical FL data and metrics">

During benchmarking, FedScale relies on a distributed setting of GPUs/CPUs via the Parameter-Server (PS) architecture. 
We have evaluated it using up to 68 GPUs to simulate FL aggregation of 1300 participants in each round. 
Each training experiment is somewhat time consuming, as each GPU has to run multiple clients (1300/68 in our case) for each round. 

**Note:**
Due to the high computation load on each GPU, we recommend limiting each GPU to simulate around 20 clients; i.e., if the number of participants in each round is K, then we would better use at least K/20 GPUs.

### Example Cost

The following are estimated prices on [Google Cloud](https://cloud.google.com/products/calculator) for training the ShuffleNet model on the OpenImage dataset using FedScale (may become inaccurate over time): 

| Setting     | Time to Target Accuracy  | Time to Converge
| ----------- | ------------------------ | ----------------
| YoGi        | 53  GPU hours (~$97)     | 121  GPU hours (~$230)


## Configuration


### Setting Up GPU Cluster

**Note:**
Please assure that these paths are consistent across all nodes so that FedScale simulator can find the right path.

- ***Coordinator node***: Make sure that the coodinator (master node) has access to other worker nodes via ```ssh```. 

- ***All nodes***: Follow [this](https://github.com/SymbioticLab/FedScale#getting-started) to install all necessary libs, and then download the datasets following [this](https://github.com/SymbioticLab/FedScale/blob/master/dataset/README.md).

### Setting Up Job Configuration

We provide an example of submitting a training job in ```FedScale/core/evals/manager.py```, whereby the user can submit jobs on the master node. 

- ```python manager.py submit [conf.yml]``` will submit a job with parameters specified in conf.yml on both the PS and worker nodes. 
We provide some example ```conf.yml``` in ```FedScale/core/evals/configs``` for each dataset. 
Comments in our example will help you quickly understand how to specify these parameters. 

- ```python manager.py stop [job_name]``` will terminate the running ```job_name``` (specified in yml) on the used nodes. 

## Dashboard

We have integrated Tensorboad for the visualization of experiment results. To track the experiment with ```[log_path]``` (e.g., ```./FedScale/core/evals/logs/cifar10/0209_141336```), please try ```tensorboard --logdir=[log_path] --bind_all```, and all the results will be available at: ```http://[ip_of_coordinator]:6006/```.

## Logs and Metrics

Meanwhile, all logs are dumped to ```log_path``` (specified in the config file) on each node. 
```testing_perf``` locates at the master node under this path, and the user can load it with ```pickle``` to check the time-to-accuracy performance. The user can also check ```/evals/[job_name]_logging``` to see whether the job is moving on.
