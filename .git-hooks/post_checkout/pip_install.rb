require_relative '../shared/pip_install'

module Overcommit::Hook::PostCheckout
  # Runs `pip install` when a change is detected in the repository's
  # dependencies.
  class PipInstall < Base
    include Overcommit::Hook::Shared::PipInstall
  end
end
