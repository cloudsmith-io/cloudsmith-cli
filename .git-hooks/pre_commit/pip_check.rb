module Overcommit
  module Hook
    module PreCommit
      # Check pip requirements.txt for parse errors
      class PipCheck < Base
        def run
          output = execute(command).stderr.split("\n")
          output.select!{ |x| x.start_with? 'RequirementParseError' }
          return :pass if output.empty?
          return [:fail, output.join("\n").gsub('RequirementParseError: ', '')]
        end
      end
    end
  end
end
