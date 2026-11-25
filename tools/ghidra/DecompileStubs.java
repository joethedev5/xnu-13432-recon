// Bulk-decompile xnu-13432 stub functions by address.
// Usage: analyzeHeadless ... -process <program> -noanalysis
//          -scriptPath tools/ghidra -postScript DecompileStubs.java <csv> <outdir>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.PrintWriter;

public class DecompileStubs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: DecompileStubs.java <csv> <outdir>");
            return;
        }
        File outdir = new File(args[1]);
        outdir.mkdirs();
        DecompInterface ifc = new DecompInterface();
        ifc.toggleCCode(true);
        ifc.toggleSyntaxTree(true);
        ifc.setSimplificationStyle("decompile");
        if (!ifc.openProgram(currentProgram)) {
            println("decompiler open failed: " + ifc.getLastMessage());
            return;
        }
        FunctionManager fm = currentProgram.getFunctionManager();
        BufferedReader br = new BufferedReader(new FileReader(args[0]));
        String line;
        int ok = 0, missing = 0, failed = 0;
        while ((line = br.readLine()) != null) {
            if (line.startsWith("#") || line.trim().isEmpty()) {
                continue;
            }
            String[] f = line.split("\t");
            long addrVal = Long.parseUnsignedLong(f[0], 16);
            String name = f[2];
            Address addr = toAddr(addrVal);
            Function fn = fm.getFunctionAt(addr);
            if (fn == null) {
                fn = fm.getFunctionContaining(addr);
            }
            if (fn == null) {
                missing++;
                println("MISSING " + name + " at " + f[0]);
                continue;
            }
            DecompileResults res = ifc.decompileFunction(fn, 60, monitor);
            if (!res.decompileCompleted()) {
                failed++;
                println("FAILED " + name + ": " + res.getErrorMessage());
                continue;
            }
            String c = res.getDecompiledFunction().getC();
            File out = new File(outdir, name + ".c");
            PrintWriter pw = new PrintWriter(out);
            pw.println("// " + name + "  " + f[0] + "  " + (f.length > 3 ? f[3] : "") + ":" + (f.length > 4 ? f[4] : ""));
            pw.println("// Ghidra decompilation of xnu-13432 kernel.release.vmapple; reference only.");
            pw.println(c);
            pw.close();
            ok++;
        }
        br.close();
        println("DECOMPILE DONE ok=" + ok + " missing=" + missing + " failed=" + failed);
    }
}
