# Copyright 2017 Google Inc. All Rights Reserved.
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

"""Implements debian support commands for buildtool."""

import logging
import os
from threading import Semaphore

from buildtool import (
    BomSourceCodeManager,
    ExecutionError,
    GradleCommandProcessor,
    GradleCommandFactory,

    check_options_set,
    raise_and_log_error,
    ConfigError)


NON_DEBIAN_BOM_REPOSITORIES = ['spin']


class BuildDebianCommand(GradleCommandProcessor):
  def __init__(self, factory, options, **kwargs):
    options.github_disable_upstream_push = True
    super(BuildDebianCommand, self).__init__(factory, options, **kwargs)
    self.__semaphore = Semaphore(options.max_local_builds)

    if not os.environ.get('BINTRAY_KEY'):
      raise_and_log_error(ConfigError('Expected BINTRAY_KEY set.'))
    if not os.environ.get('BINTRAY_USER'):
      raise_and_log_error(ConfigError('Expected BINTRAY_USER set.'))
    check_options_set(
        options, ['bintray_org', 'bintray_jar_repository',
                  'bintray_debian_repository', 'bintray_publish_wait_secs'])

  def _do_can_skip_repository(self, repository):
    if repository.name in NON_DEBIAN_BOM_REPOSITORIES:
      return True

    build_version = self.scm.get_repository_service_build_version(repository)
    return self.gradle.consider_debian_on_bintray(repository, build_version)

  def _do_repository(self, repository):
    """Implements RepositoryCommandProcessor interface."""
    args = self._do_repository_args(repository, False)

    # TODO(joonlim): cfieber is currently updating the services to use Spring
    # Boot 2 one by one, which breaks the command below for the service being
    # updated. Since we cannot ensure when cfieber will be finished, we will
    # attempt the command that works before cfieber's update and the command
    # that works after the update.
    try:
      with self.__semaphore:
        self.gradle.check_run(args, self, repository, 'candidate', 'debian-build')
    except ExecutionError:
      logging.info('Failed to run "./gradlew candidate" command with'
                  ' "-I gradle/init-publish.gradle" flag for service {}.'
                  ' Rerunning with "-PenabledPublishing=true" flag. Please'
                  ' always run this command with the "-PenabledPublishing=true"'
                  ' flag once all services have been updated to use Spring Boot 2.'.format(repository.name))

      args = self._do_repository_args(repository, True)
      with self.__semaphore:
        self.gradle.check_run(args, self, repository, 'candidate', 'debian-build')

  def _do_repository_args(self, repository, new_publish_flag):
    options = self.options
    args = self.gradle.get_common_args()
    if options.gradle_cache_path:
      args.append('--gradle-user-home=' + options.gradle_cache_path)

    if (not options.run_unit_tests
        or (name == 'deck' and not 'CHROME_BIN' in os.environ)):
      args.append('-x test')

    if new_publish_flag:
      args.append('-PenabledPublishing=true')
    elif (os.path.isfile(os.path.join(repository.git_dir, "gradle", "init-publish.gradle"))):
      args.append('-I gradle/init-publish.gradle')

    args.extend(self.gradle.get_debian_args('trusty,xenial,bionic'))
    return args

def add_bom_parser_args(parser, defaults):
  """Adds parser arguments pertaining to publishing boms."""
  # These are implemented by the gradle factory, but conceptually
  # for debians, so are exported this way.
  GradleCommandFactory.add_bom_parser_args(parser, defaults)


def register_commands(registry, subparsers, defaults):
  build_debian_factory = GradleCommandFactory(
      'build_debians', BuildDebianCommand,
      'Build one or more debian packages from the local git repository.',
      BomSourceCodeManager)

  build_debian_factory.register(registry, subparsers, defaults)
