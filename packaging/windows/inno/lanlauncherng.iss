#define MyAppName "LANLauncherNG"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#ifndef PackageRoot
  #define PackageRoot "dist\\windows\\lanlauncher"
#endif
#define MyAppPublisher "LANLauncherNG"
#define MyAppExeName "run.bat"

[Setup]
AppId={{D2B0736A-8A7E-4FC1-B3C8-2C93EE34F4E1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
SetupIconFile=..\..\..\src\frontend\assets\icons\lanlauncherng.ico
UninstallDisplayIcon={app}\app\src\frontend\assets\icons\lanlauncherng.ico
DefaultDirName={autopf}\LANLauncherNG
DefaultGroupName=LANLauncherNG
DisableProgramGroupPage=yes
OutputDir=..\..\..\dist\windows\installer
OutputBaseFilename=lanlauncherng-setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
english.InstallDokan=Install the Dokany 2.3 filesystem driver required for temporary Ouisync mounts (administrator approval required)
german.InstallDokan=Den Dokany-2.3-Dateisystemtreiber für temporäre Ouisync-Mounts installieren (Administratorbestätigung erforderlich)
english.DokanInstallStatus=Installing the Dokany filesystem driver...
german.DokanInstallStatus=Dokany-Dateisystemtreiber wird installiert...
english.DokanInstallFailed=The Dokany driver could not be installed. Temporary Ouisync mounts will not work.
german.DokanInstallFailed=Der Dokany-Treiber konnte nicht installiert werden. Temporäre Ouisync-Mounts funktionieren dann nicht.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "dokan"; Description: "{cm:InstallDokan}"; GroupDescription: "Ouisync"

[Files]
Source: "{#PackageRoot}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Code]
var
  DokanRestartRequired: Boolean;

function NeedRestart(): Boolean;
begin
  Result := DokanRestartRequired;
end;

function IsDokanDriverInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{sys}\drivers\dokan2.sys'));
end;

procedure CopyOptionalInstallerAsset(const SourceName, DestPath: string);
var
  SourcePath: string;
  DestDir: string;
begin
  SourcePath := ExtractFilePath(ExpandConstant('{srcexe}')) + SourceName;
  if not FileExists(SourcePath) then begin
    Exit;
  end;

  DestDir := ExtractFileDir(ExpandConstant(DestPath));
  if DestDir <> '' then begin
    ForceDirectories(DestDir);
  end;

  if not CopyFile(SourcePath, ExpandConstant(DestPath), False) then begin
    RaiseException('Failed to copy optional asset: ' + SourceName);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  InstallerPath: string;
begin
  if CurStep <> ssPostInstall then begin
    Exit;
  end;

  if WizardIsTaskSelected('dokan') and not IsDokanDriverInstalled() then begin
    WizardForm.StatusLabel.Caption := ExpandConstant('{cm:DokanInstallStatus}');
    InstallerPath := ExpandConstant('{app}\vendor\bin\windows-amd64\Dokan_x64.msi');
    if not Exec(
      ExpandConstant('{sys}\msiexec.exe'),
      '/i "' + InstallerPath + '" /qn /norestart',
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    ) then begin
      RaiseException(ExpandConstant('{cm:DokanInstallFailed}'));
    end;
    if (ResultCode <> 0) and (ResultCode <> 3010) and (ResultCode <> 1641) then begin
      RaiseException(ExpandConstant('{cm:DokanInstallFailed}'));
    end;
    if (ResultCode = 3010) or (ResultCode = 1641) then begin
      DokanRestartRequired := True;
    end;
  end;

  // Allow local admins to drop their own Resilio binary, license, and presets
  // next to the installer so the setup can stage them into the install root.
  CopyOptionalInstallerAsset(
    'btsync.exe',
    '{app}\vendor\bin\windows-amd64\btsync.exe'
  );
  CopyOptionalInstallerAsset(
    'llng.btskey',
    '{app}\vendor\licenses\resilio\llng.btskey'
  );
  CopyOptionalInstallerAsset(
    'bootstrap.json',
    '{app}\config\optional-bootstrap.json'
  );
end;

[Icons]
Name: "{autoprograms}\LANLauncherNG"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app\src\frontend\assets\icons\lanlauncherng.ico"
Name: "{autodesktop}\LANLauncherNG"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\app\src\frontend\assets\icons\lanlauncherng.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start LANLauncherNG"; Flags: nowait postinstall skipifsilent runminimized
