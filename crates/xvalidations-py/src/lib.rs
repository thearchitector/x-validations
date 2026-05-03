use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pythonize::{depythonize, pythonize};
use serde_json::Value;
use xvalidations_core::{xvalidate as core_xvalidate, XValidationFailure};

#[pyfunction]
fn xvalidate(
    py: Python<'_>,
    payload: &Bound<'_, PyAny>,
    schema: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let payload_value: Value = depythonize(payload).map_err(|error| {
        PyTypeError::new_err(format!("payload must be JSON-compatible: {error}"))
    })?;
    let schema_value: Value = depythonize(schema).map_err(|error| {
        PyTypeError::new_err(format!("schema must be JSON-compatible: {error}"))
    })?;

    match core_xvalidate(&payload_value, &schema_value) {
        Ok(()) => Ok(()),
        Err(failure) => Err(failure_to_py_err(py, failure)?),
    }
}

fn failure_to_py_err(py: Python<'_>, failure: XValidationFailure) -> PyResult<PyErr> {
    let class_name = match failure {
        XValidationFailure::Validation { .. } => "XValidationError",
        XValidationFailure::InvalidSchema { .. } => "ExportedSchemaError",
        XValidationFailure::InvalidRule { .. } => "InvalidRuleError",
        XValidationFailure::JsonPath { .. } => "JsonPathError",
        XValidationFailure::Resolve { .. } => "ResolveError",
    };
    let failure = serde_json::to_value(&failure).map_err(|error| {
        PyTypeError::new_err(format!("failed to serialize validation failure: {error}"))
    })?;
    let failure = pythonize(py, &failure)?;
    let errors = py.import("xvalidations.errors")?;
    let error_type = errors.getattr(class_name)?;
    let exception = error_type.call1((failure,))?;
    Ok(PyErr::from_value(exception))
}

#[pymodule]
fn _xvalidations(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(xvalidate, m)?)?;
    Ok(())
}
