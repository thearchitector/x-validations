use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyList;
use pythonize::{depythonize, pythonize};
use serde_json::Value;
use xvalidations_core::{
    xvalidate as core_xvalidate, ValidationError as CoreValidationError, XValidationBindingFailure,
    XValidationFailure,
};

pyo3::create_exception!(xvalidate, ExportedSchemaError, PyValueError);
pyo3::create_exception!(xvalidate, InvalidRuleError, ExportedSchemaError);
pyo3::create_exception!(xvalidate, JsonPathError, ExportedSchemaError);
pyo3::create_exception!(xvalidate, ResolveError, ExportedSchemaError);
pyo3::create_exception!(xvalidate, XValidationTypeError, PyTypeError);
pyo3::create_exception!(xvalidate, XValidationError, PyValueError);

#[pyclass(frozen, skip_from_py_object)]
#[derive(Clone, Debug, Eq, PartialEq)]
struct ValidationError {
    #[pyo3(get)]
    path: String,
    #[pyo3(get)]
    message: String,
    #[pyo3(get)]
    keyword: Option<String>,
    #[pyo3(get)]
    source: String,
    #[pyo3(get)]
    rule_id: Option<String>,
}

impl From<&CoreValidationError> for ValidationError {
    fn from(error: &CoreValidationError) -> Self {
        Self {
            path: error.path.clone(),
            message: error.message.clone(),
            keyword: error.keyword.clone(),
            source: error.source.as_str().to_string(),
            rule_id: error.rule_id.clone(),
        }
    }
}

#[pyfunction(name = "xvalidate")]
fn validate(py: Python<'_>, payload: &Bound<'_, PyAny>, schema: &Bound<'_, PyAny>) -> PyResult<()> {
    let payload_value: Value = depythonize(payload).map_err(|error| {
        conversion_failure_to_py_err(
            py,
            "invalid_payload",
            &format!("payload must be JSON-compatible: {error}"),
        )
    })?;
    let schema_value: Value = depythonize(schema).map_err(|error| {
        conversion_failure_to_py_err(
            py,
            "invalid_schema_input",
            &format!("schema must be JSON-compatible: {error}"),
        )
    })?;

    match py.detach(|| core_xvalidate(&payload_value, &schema_value)) {
        Ok(()) => Ok(()),
        Err(failure) => Err(failure_to_py_err(py, failure)?),
    }
}

fn failure_to_py_err(py: Python<'_>, failure: XValidationFailure) -> PyResult<PyErr> {
    let exception = py
        .import("xvalidate")?
        .getattr(failure.exception_name())?
        .call1((failure.to_string(),))?;
    if let Some(errors) = failure.errors() {
        let error_objects = PyList::new(
            py,
            errors
                .iter()
                .map(|error| Py::new(py, ValidationError::from(error)))
                .collect::<PyResult<Vec<_>>>()?,
        )?;
        exception.setattr("errors", error_objects)?;
    }
    add_core_failure_attrs(py, &exception, &failure)?;
    Ok(PyErr::from_value(exception))
}

fn add_core_failure_attrs(
    py: Python<'_>,
    exception: &Bound<'_, PyAny>,
    failure: &XValidationFailure,
) -> PyResult<()> {
    exception.setattr("failure", failure_to_py_object(py, failure)?)?;
    exception.setattr("kind", failure.kind())?;
    Ok(())
}

fn conversion_failure_to_py_err(py: Python<'_>, kind: &str, message: &str) -> PyErr {
    conversion_failure_to_py_exception(py, &XValidationBindingFailure::new(kind, message))
        .unwrap_or_else(|error| error)
}

fn conversion_failure_to_py_exception(
    py: Python<'_>,
    failure: &XValidationBindingFailure,
) -> PyResult<PyErr> {
    let exception = py
        .get_type::<XValidationTypeError>()
        .call1((failure.message.as_str(),))?;
    exception.setattr("failure", binding_failure_to_py_object(py, failure)?)?;
    exception.setattr("kind", failure.kind.as_str())?;
    Ok(PyErr::from_value(exception))
}

fn failure_to_py_object<'py>(
    py: Python<'py>,
    failure: &XValidationFailure,
) -> PyResult<Bound<'py, PyAny>> {
    let failure = failure.to_json_value().map_err(|error| {
        PyTypeError::new_err(format!("failed to serialize validation failure: {error}"))
    })?;
    Ok(pythonize(py, &failure)?)
}

fn binding_failure_to_py_object<'py>(
    py: Python<'py>,
    failure: &XValidationBindingFailure,
) -> PyResult<Bound<'py, PyAny>> {
    let failure = failure.to_json_value().map_err(|error| {
        PyTypeError::new_err(format!("failed to serialize binding failure: {error}"))
    })?;
    Ok(pythonize(py, &failure)?)
}

#[pymodule]
fn xvalidate(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(validate, m)?)?;
    m.add_class::<ValidationError>()?;
    m.add("ExportedSchemaError", py.get_type::<ExportedSchemaError>())?;
    m.add("InvalidRuleError", py.get_type::<InvalidRuleError>())?;
    m.add("JsonPathError", py.get_type::<JsonPathError>())?;
    m.add("ResolveError", py.get_type::<ResolveError>())?;
    m.add(
        "XValidationTypeError",
        py.get_type::<XValidationTypeError>(),
    )?;
    m.add("XValidationError", py.get_type::<XValidationError>())?;
    m.add(
        "__all__",
        vec![
            "ExportedSchemaError",
            "InvalidRuleError",
            "JsonPathError",
            "ResolveError",
            "ValidationError",
            "XValidationTypeError",
            "XValidationError",
            "xvalidate",
        ],
    )?;
    Ok(())
}
