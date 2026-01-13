'use client'

import ContractUpload from '@/app/components/ContractUpload'

export default function ContractUploadPage() {
  return (
    <main className="min-h-screen bg-stone-50 p-8">
      <div className="max-w-4xl mx-auto">
        <header className="mb-12">
          <h1 className="text-4xl font-bold text-stone-900" style={{ fontFamily: 'Playfair Display, serif' }}>
            Upload Contract
          </h1>
          <p className="text-stone-600 mt-2">
            Upload a PDF or DOCX contract for automated parsing and clause extraction
          </p>
        </header>

        <ContractUpload />
      </div>
    </main>
  )
}
