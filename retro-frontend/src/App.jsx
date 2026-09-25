import React, { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import "./App.css"; // Import the custom CSS (see below)

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function App() {
  const [file, setFile] = useState(null);
  const [uploadMessage, setUploadMessage] = useState("");
  const [query, setQuery] = useState("");
  const [responseData, setResponseData] = useState(null);
  const [loadingQuery, setLoadingQuery] = useState(false);
  const [stats, setStats] = useState(null);
  const [refreshStats, setRefreshStats] = useState(false);
  const [modalImage, setModalImage] = useState(null);
  const [selectedFiles, setSelectedFiles] = useState([]);


  // Fetch stats for uploaded files on mount and when refreshStats toggles.
  useEffect(() => {
    fetch(`${API_URL}/stats`)
      .then((res) => res.json())
      .then((data) => setStats(data))
      .catch((err) => console.error("Error fetching stats:", err));
  }, [refreshStats]);

  useEffect(() => {
    if (stats && stats.filenames) {
      setSelectedFiles(stats.filenames); // Enable all by default
    }
  }, [stats]);

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
  };

  const handleUpload = async () => {
    if (!file) {
      setUploadMessage("Please select a PDF file to upload.");
      return;
    }
    setUploadMessage("Uploading...");
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(`${API_URL}/upload`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      const text = await res.text();
      const data = text ? JSON.parse(text) : {};
      if (data.error) throw new Error(data.error);
      setUploadMessage(`Upload successful: ${data.filename}`);
      setSelectedFiles((prev) => [...prev, data.filename]);
      setRefreshStats((prev) => !prev);

    } catch (error) {
      console.error(error);
      setUploadMessage("Upload failed.");
    }
  };

  const handleQuery = async () => {
    if (!query.trim()) return;
    setLoadingQuery(true);
    setResponseData(null);
    try {
      const formData = new FormData();
      formData.append("q", query);
      formData.append("allowed_files", selectedFiles.join(","));
      const res = await fetch(`${API_URL}/query`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      const data = await res.json();

      // The backend already keeps only the images the model marked as relevant.
      setResponseData(data);
      console.log("Query response:", data);
    } catch (error) {
      console.error(error);
    } finally {
      setLoadingQuery(false);
    }
  };



  const handleDelete = async (filename) => {
    if (!window.confirm(`Delete all segments from ${filename}?`)) return;
    try {
      const res = await fetch(
        `${API_URL}/delete_document?filename=${encodeURIComponent(filename)}`,
        { method: "DELETE" }
      );
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      const data = await res.json();
      console.log("Deleted:", data);
      setRefreshStats((prev) => !prev);
    } catch (error) {
      console.error("Error deleting file:", error);
    }
  };

  const closeModal = () => {
    setModalImage(null);
  };

  return (
    <div className="animated-bg min-h-screen p-8 font-mono text-white">
      {/* Header with Site Name */}
      <header className="mb-8 text-center">
        <h1 className="text-5xl font-bold tracking-widest retro-font">
          RetroDoc
        </h1>
        <p className="mt-2 text-xl text-gray-300">Your Retro Document Analyzer</p>
      </header>
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row gap-8">
        {/* Sidebar */}
        <aside className="w-full md:w-1/3 bg-gray-800 bg-opacity-90 p-6 border-2 border-gray-700 shadow-xl">
          {/* 1. Uploaded Files */}
          <div>
            <h2 className="text-3xl font-bold text-green-400 mb-4 border-b border-green-400 pb-2">
              Uploaded Files
            </h2>
            {stats && stats.filenames ? (
              <ul className="space-y-3 max-h-48 overflow-y-auto pr-2">
                {stats.filenames.map((fname, idx) => {
                  const isSelected = selectedFiles.includes(fname);
                  return (
                    <li
                      key={idx}
                      className="flex justify-between items-center border-b border-gray-700 pb-1 text-sm text-gray-300"
                    >
                      <div>
                        <span className="font-bold">{fname}</span>
                        <button
                          onClick={() =>
                            setSelectedFiles((prev) =>
                              isSelected
                                ? prev.filter((f) => f !== fname)
                                : [...prev, fname]
                            )
                          }
                          className={`ml-2 px-2 py-1 rounded text-xs ${isSelected
                            ? "bg-green-600 hover:bg-green-700"
                            : "bg-yellow-600 hover:bg-yellow-700"
                            }`}
                        >
                          {isSelected ? "Enabled" : "Disabled"}
                        </button>
                      </div>
                      <button
                        onClick={() => handleDelete(fname)}
                        className="text-red-500 hover:text-red-700 text-xs"
                      >
                        Delete
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-sm text-gray-500">No files uploaded.</p>
            )}

          </div>
          {/* 2. Upload PDF */}
          <div>
            <h2 className="text-3xl font-bold text-green-400 mb-4 border-b border-green-400 pb-2">
              Upload PDF
            </h2>
            <div className="flex flex-col gap-4">
              <input
                type="file"
                accept="application/pdf"
                onChange={handleFileChange}
                className="block w-full bg-gray-700 text-gray-200 p-2 border border-gray-600"
              />
              <button
                onClick={handleUpload}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded shadow transition"
              >
                Upload
              </button>
              {uploadMessage && (
                <p className="text-sm text-center text-gray-300">
                  {uploadMessage}
                </p>
              )}
            </div>
          </div>
          {/* 3. Query Documents */}
          <div>
            <h2 className="text-3xl font-bold text-green-400 mb-4 border-b border-green-400 pb-2">
              Query Documents
            </h2>
            <div className="flex flex-col gap-4">
              <input
                type="text"
                placeholder="Enter your query..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full p-3 bg-gray-700 text-gray-200 border border-gray-600 rounded focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
              <button
                onClick={handleQuery}
                className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded shadow transition"
              >
                {loadingQuery ? "Searching..." : "Search"}
              </button>
            </div>
          </div>
          {/* 4. Response Sources */}
          {responseData && responseData.retrieved_context && (
            <div>
              <h2 className="text-3xl font-bold text-green-400 mb-4 border-b border-green-400 pb-2">
                Response Sources
              </h2>
              <ul className="space-y-3 max-h-48 overflow-y-auto pr-2">
                {responseData.retrieved_context.map((item, idx) => (
                  <li key={idx} className="text-xs text-gray-300 border-b border-gray-700 pb-1">
                    <span className="font-bold">
                      {item.filename} (Page{" "}
                      {typeof item.page !== "undefined"
                        ? item.page
                        : item.page_num + 1}
                      )
                    </span>
                    : {item.text.slice(0, 100)}...
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>

        {/* Main Content */}
        <main className="w-full md:w-2/3 bg-gray-100 text-gray-900 p-8 border-2 border-gray-300 rounded shadow-2xl">
          {responseData ? (
            <>
              {/* Generated Response */}
              <section className="w-full">
                <h2 className="text-3xl font-bold mb-4 border-b border-gray-400 pb-2">
                  Generated Response
                </h2>
                <div className="prose max-w-none">
                  {typeof responseData.generated_response === "object" ? (
                    <ReactMarkdown>
                      {[
                        responseData.generated_response.text_analysis,
                        responseData.generated_response.final_answer,
                      ]
                        .filter(Boolean)
                        .join("\n\n")}
                    </ReactMarkdown>
                  ) : (
                    <ReactMarkdown>
                      {responseData.generated_response}
                    </ReactMarkdown>
                  )}
                </div>
              </section>
              {/* Visual Sources */}
              {responseData.retrieved_images &&
                responseData.retrieved_images.length > 0 && (
                  <section className="w-full">
                    <h2 className="text-3xl font-bold mb-4 border-b border-gray-400 pb-2">
                      Visual Sources
                    </h2>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                      {responseData.retrieved_images.map((img, idx) => (
                        <div
                          key={idx}
                          className="bg-gray-200 rounded shadow hover:shadow-2xl transition transform hover:-translate-y-1 cursor-pointer"
                          onClick={() =>
                            setModalImage(
                              img.image_url ||
                              `data:image/jpeg;base64,${img.image_b64 || ""}`
                            )
                          }
                        >
                          <img
                            src={
                              img.image_url ||
                              `data:image/jpeg;base64,${img.image_b64 || ""}`
                            }
                            alt={img.desc || "Document image"}
                            className="w-full h-56 object-cover rounded-t"
                          />
                          <div className="p-4">
                            <p className="text-sm font-semibold">
                              {img.filename}{" "}
                              <span className="text-xs text-gray-600">
                                (Page{" "}
                                {typeof img.page !== "undefined"
                                  ? img.page
                                  : img.page_num + 1}
                                )
                              </span>
                            </p>
                            {responseData.generated_response?.image_analysis?.[idx] && (
                              <p className="mt-1 text-xs text-gray-600 italic">
                                {responseData.generated_response.image_analysis[idx]}
                              </p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
            </>
          ) : (
            <div className="text-center">
              <p className="text-2xl">Enter a query to see results.</p>
            </div>
          )}
        </main>
      </div>

      {/* Modal for Image Zoom */}
      {modalImage && (
        <div
          className="fixed inset-0 bg-black bg-opacity-80 flex items-center justify-center z-50"
          onClick={closeModal}
        >
          <div className="relative max-w-4xl max-h-full">
            <img
              src={modalImage}
              alt="Zoomed document"
              className="object-contain rounded"
            />
            <button
              className="absolute top-4 right-4 text-white bg-gray-800 rounded-full p-3 hover:bg-gray-700 transition"
              onClick={closeModal}
            >
              ×
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
