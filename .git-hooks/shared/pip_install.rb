module Overcommit::Hook::Shared
  # Shared code used by all PipInstall hooks. Runs `pip install` when a change
  # is detected in the repository's dependencies.
  module PipInstall
    def run
      result = execute(command)
      return :fail, result.stderr unless result.success?
      :pass
    end
  end
end
