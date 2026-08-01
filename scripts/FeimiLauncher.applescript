try
  set launcherPath to (system attribute "HOME") & "/Library/Application Support/Feimi/scripts/feimi-start.sh"
  do shell script quoted form of launcherPath
on error errorMessage
  display dialog "飞觅启动失败：" & return & errorMessage buttons {"好"} default button "好" with icon stop
end try
