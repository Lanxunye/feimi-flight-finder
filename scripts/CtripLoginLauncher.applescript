try
  set launcherPath to (system attribute "HOME") & "/Library/Application Support/Feimi/scripts/ctrip-login.sh"
  do shell script quoted form of launcherPath
on error errorMessage
  display dialog "携程专用浏览器启动失败：" & return & errorMessage buttons {"好"} default button "好" with icon stop
end try
