import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { FileText, Upload } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { useState } from "react";

interface ContractsSectionProps {
  onSectionChange: (section: string) => void;
}

export function ContractsSection({ onSectionChange }: ContractsSectionProps) {
  const [dragActive, setDragActive] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setUploadedFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setUploadedFiles(Array.from(e.target.files));
    }
  };

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-slate-900 mb-6 font-[Libre_Baskerville] text-2xl font-bold">Digitize your documents</h1>
        
        {/* File Upload Box */}
        <Card>
          <CardContent className="p-4">
            <div
              className={`relative border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
                dragActive
                  ? "border-blue-500 bg-blue-50"
                  : "border-slate-300 bg-slate-50 hover:border-slate-400"
              }`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
            >
              <input
                type="file"
                id="file-upload"
                multiple
                onChange={handleFileChange}
                className="hidden"
              />
              <div className="flex flex-col items-center gap-2">
                <div className="p-3 bg-slate-100 rounded-full">
                  <Upload className="w-6 h-6 text-slate-600" />
                </div>
                <div>
                  <p className="text-slate-900 mb-1">
                    Drag and drop files here, or{" "}
                    <label
                      htmlFor="file-upload"
                      className="text-blue-600 hover:text-blue-700 cursor-pointer underline"
                    >
                      browse
                    </label>
                  </p>
                  <p className="text-sm text-slate-500">
                    Support for PDF, DOCX, images and more
                  </p>
                </div>
                <Button
                  onClick={() => document.getElementById("file-upload")?.click()}
                  variant="outline"
                >
                  Select Files
                </Button>
              </div>
            </div>

            {uploadedFiles.length > 0 && (
              <div className="mt-4 space-y-2">
                <p className="text-sm text-slate-600">Selected files:</p>
                {uploadedFiles.map((file, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between p-3 bg-slate-50 rounded-lg"
                  >
                    <div className="flex items-center gap-3">
                      <FileText className="w-4 h-4 text-slate-600" />
                      <span className="text-sm text-slate-900">{file.name}</span>
                      <span className="text-xs text-slate-500">
                        ({(file.size / 1024).toFixed(1)} KB)
                      </span>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        setUploadedFiles(uploadedFiles.filter((_, i) => i !== index))
                      }
                    >
                      Remove
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div>
        <h1 className="text-slate-900 mb-2 font-[Libre_Baskerville] text-2xl font-bold">Contracts Hub</h1>
      </div>

      <Card>
        <CardHeader>
          <Input placeholder="Search contracts..." />
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[
              { name: "PPA - Sunfield Solar Park", term: "20 years", expiry: "Dec 2043", status: "active" },
              { name: "PPA - Windridge Energy Farm", term: "15 years", expiry: "Jun 2038", status: "active" },
              { name: "PPA - Coastal Renewable Hub", term: "10 years", expiry: "Mar 2028", status: "renewal" },
              { name: "PPA - Metro Grid Storage", term: "10 years", expiry: "Sep 2033", status: "active" },
              { name: "PPA - Desert Sun Array", term: "5 years", expiry: "Nov 2030", status: "active" },
            ].map((contract, index) => (
              <div
                key={index}
                className={`flex items-center gap-4 p-4 rounded-lg border border-slate-200 ${
                  contract.name === "PPA - Sunfield Solar Park"
                    ? "cursor-pointer hover:border-slate-400 transition-colors"
                    : ""
                }`}
                onClick={() => {
                  if (contract.name === "PPA - Sunfield Solar Park") {
                    onSectionChange("ppa-summary");
                  }
                }}
              >
                <div className="p-3 rounded-lg bg-orange-50">
                  <FileText className="w-5 h-5 text-orange-600" />
                </div>
                <div className="flex-1">
                  <div className="text-slate-900 mb-1">{contract.name}</div>
                  <div className="text-sm text-slate-500">
                    {contract.term} • Expires {contract.expiry}
                  </div>
                </div>
                <Badge
                  variant="outline"
                  className={
                    contract.status === "active"
                      ? "text-green-600 border-green-200 bg-green-50"
                      : "text-orange-600 border-orange-200 bg-orange-50"
                  }
                >
                  {contract.status}
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}