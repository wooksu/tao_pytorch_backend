# Copyright (c) 2023, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

""" MMClassification Train Module """

from nvidia_tao_pytorch.core.hydra.hydra_runner import hydra_runner
from nvidia_tao_pytorch.core.mmlab.mmclassification.classification_default_config import ExperimentConfig
from nvidia_tao_pytorch.core.mmlab.mmclassification.utils import MMPretrainConfig
from nvidia_tao_pytorch.cv.classification.heads import *  # noqa pylint: disable=W0401, W0614
from nvidia_tao_pytorch.cv.classification.models import *  # noqa pylint: disable=W0401, W0614
from nvidia_tao_pytorch.core.mmlab.mmclassification.logistic_regression_trainer import LogisticRegressionTrainer as LRTrainer
from nvidia_tao_pytorch.core.mmlab.common.utils import get_latest_pth_model
import nvidia_tao_pytorch.core.loggers.api_logging as status_logging

import torch
from mmengine.runner import Runner

import os
import warnings

warnings.filterwarnings('ignore')


def run_experiment(experiment_config, results_dir):
    """Start the training."""
    os.makedirs(results_dir, exist_ok=True)
    # Set status logging

    status_file = os.path.join(results_dir, "status.json")
    status_logging.set_status_logger(
        status_logging.StatusLogger(
            filename=status_file,
            append=True
        )
    )
    status_logging.get_status_logger().write(
        status_level=status_logging.Status.STARTED,
        message="Starting Classification Train"
    )
    status_logger = status_logging.get_status_logger()
    status_logger.write(message="********************** Start logging for Training **********************.")
    mmpretrain_config = MMPretrainConfig(experiment_config, phase="train")
    train_cfg = mmpretrain_config.updated_config
    train_cfg["work_dir"] = results_dir
    if experiment_config.model.head.type == "LogisticRegressionHead":
        lr_trainer = LRTrainer(train_cfg=experiment_config,
                               updated_config=train_cfg,
                               status_logger=status_logger)
        lr_trainer.fit()
        model = lr_trainer.model
        model.eval()
        checkpoint = {}
        with torch.no_grad():
            weights = lr_trainer.classifier.coef_
            model.head.fc.weight.data.copy_(torch.from_numpy(weights))
            biases = lr_trainer.classifier.intercept_
            model.head.fc.bias.data.copy_(torch.from_numpy(biases))
        checkpoint['state_dict'] = model.state_dict()
        torch.save(checkpoint, os.path.join(results_dir, "model_lrHead_0.pth"))

    else:
        resume_checkpoint = get_latest_pth_model(results_dir)
        if resume_checkpoint:
            train_cfg["load_from"] = resume_checkpoint
            train_cfg["resume"] = True
            train_cfg["model"]["backbone"]["init_cfg"] = None  # Disable pretrained weights if there are any
        train_cfg["work_dir"] = results_dir
        if "mit" in train_cfg["model"]["backbone"]["type"]:
            lr_updated = train_cfg["optim_wrapper"]["optimizer"]["lr"] * train_cfg["auto_scale_lr"]["base_batch_size"] / 512
            train_cfg["optim_wrapper"]["optimizer"]["lr"] = lr_updated
            runner = Runner.from_cfg(train_cfg)
        runner.train()


spec_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Load experiment specification, additially using schema for validation/retrieving the default values.
# --config_path and --config_name will be provided by the entrypoint script.


@hydra_runner(
    config_path=os.path.join(spec_root, "experiment_specs"), config_name="train_cats_dogs_new_fan", schema=ExperimentConfig
)
def main(cfg: ExperimentConfig) -> None:
    """Run the training process."""
    try:
        if cfg.train.results_dir is not None:
            results_dir = cfg.train.results_dir
        else:
            results_dir = os.path.join(cfg.results_dir, "train")

        run_experiment(cfg, results_dir=results_dir)
        status_logging.get_status_logger().write(status_level=status_logging.Status.SUCCESS,
                                                 message="Training finished successfully.")
    except (KeyboardInterrupt, SystemExit):
        status_logging.get_status_logger().write(
            message="Training was interrupted",
            verbosity_level=status_logging.Verbosity.INFO,
            status_level=status_logging.Status.FAILURE
        )
    except Exception as e:
        status_logging.get_status_logger().write(
            message=str(e),
            status_level=status_logging.Status.FAILURE
        )
        raise e


if __name__ == "__main__":
    main()
