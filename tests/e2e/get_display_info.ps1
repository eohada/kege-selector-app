Add-Type @'
using System;
using System.Runtime.InteropServices;

public class DisplayHelper {
    [DllImport("user32.dll")]
    public static extern bool EnumDisplaySettings(string deviceName, int modeNum, ref DEVMODE devMode);

    [StructLayout(LayoutKind.Sequential)]
    public struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        public string dmDeviceName;
        public short dmSpecVersion;
        public short dmDriverVersion;
        public short dmSize;
        public short dmDriverExtra;
        public int dmFields;
        public int dmPositionX;
        public int dmPositionY;
        public int dmDisplayOrientation;
        public int dmDisplayFixedOutput;
        public short dmColor;
        public short dmDuplex;
        public short dmYResolution;
        public short dmTTOption;
        public short dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        public string dmFormName;
        public short dmLogPixels;
        public int dmBitsPerPel;
        public int dmPelsWidth;
        public int dmPelsHeight;
        public int dmDisplayFlags;
        public int dmDisplayFrequency;
    }

    public static void PrintDisplays() {
        foreach (var screen in System.Windows.Forms.Screen.AllScreens) {
            DEVMODE dm = new DEVMODE();
            dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
            if (EnumDisplaySettings(screen.DeviceName, -1, ref dm)) {
                Console.WriteLine(screen.DeviceName + ": " + dm.dmPelsWidth + "x" + dm.dmPelsHeight + " @ " + dm.dmDisplayFrequency + "Hz, Bounds: " + screen.Bounds + " (Primary=" + screen.Primary + ")");
            }
        }
    }
}
'@ -ReferencedAssemblies System.Windows.Forms, System.Drawing

[DisplayHelper]::PrintDisplays()
