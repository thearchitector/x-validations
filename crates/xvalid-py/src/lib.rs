use pyo3::class::basic::CompareOp;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyList;
use pythonize::{depythonize, pythonize};
use serde_json::Value;
use xvalidations_core::{
    xvalidate as core_xvalidate, ValidationIssue as CoreValidationIssue, XValidationBindingFailure,
    XValidationFailure,
};

pyo3::create_exception!(xvalid, ExportedSchemaError, PyValueError);
pyo3::create_exception!(xvalid, InvalidRuleError, ExportedSchemaError);
pyo3::create_exception!(xvalid, JsonPathError, ExportedSchemaError);
pyo3::create_exception!(xvalid, ResolveError, ExportedSchemaError);
pyo3::create_exception!(xvalid, XValidationTypeError, PyTypeError);
pyo3::create_exception!(xvalid, XValidationError, PyValueError);

#[pyclass(frozen, skip_from_py_object)]
#[derive(Clone, Debug, Eq, PartialEq)]
struct ValidationIssue {
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

#[pymethods]
impl ValidationIssue {
    #[new]
    fn new(
        path: String,
        message: String,
        keyword: Option<String>,
        source: String,
        rule_id: Option<String>,
    ) -> Self {
        Self {
            path,
            message,
            keyword,
            source,
            rule_id,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "ValidationIssue(path={:?}, message={:?}, keyword={:?}, source={:?}, rule_id={:?})",
            self.path, self.message, self.keyword, self.source, self.rule_id
        )
    }

    fn __richcmp__(&self, other: PyRef<'_, ValidationIssue>, op: CompareOp) -> bool {
        match op {
            CompareOp::Eq => self == &*other,
            CompareOp::Ne => self != &*other,
            _ => false,
        }
    }
}

impl From<&CoreValidationIssue> for ValidationIssue {
    fn from(issue: &CoreValidationIssue) -> Self {
        Self {
            path: issue.path.clone(),
            message: issue.message.clone(),
            keyword: issue.keyword.clone(),
            source: issue.source.as_str().to_string(),
            rule_id: issue.rule_id.clone(),
        }
    }
}

#[pyfunction]
fn xvalidate(
    py: Python<'_>,
    payload: &Bound<'_, PyAny>,
    schema: &Bound<'_, PyAny>,
) -> PyResult<()> {
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
    let exception = match &failure {
        XValidationFailure::Validation { issues } => {
            validation_failure_to_py_err(py, &failure, issues)?
        }
        XValidationFailure::InvalidSchema { .. } => py
            .get_type::<ExportedSchemaError>()
            .call1((failure.to_string(),))?,
        XValidationFailure::InvalidRule { .. } => py
            .get_type::<InvalidRuleError>()
            .call1((failure.to_string(),))?,
        XValidationFailure::JsonPath { .. } => py
            .get_type::<JsonPathError>()
            .call1((failure.to_string(),))?,
        XValidationFailure::Resolve { .. } => py
            .get_type::<ResolveError>()
            .call1((failure.to_string(),))?,
    };
    add_core_failure_attrs(py, &exception, &failure)?;
    Ok(PyErr::from_value(exception))
}

fn validation_failure_to_py_err<'py>(
    py: Python<'py>,
    failure: &XValidationFailure,
    issues: &[CoreValidationIssue],
) -> PyResult<Bound<'py, PyAny>> {
    let issue_objects = PyList::new(
        py,
        issues
            .iter()
            .map(|issue| Py::new(py, ValidationIssue::from(issue)))
            .collect::<PyResult<Vec<_>>>()?,
    )?;
    let exception = py
        .get_type::<XValidationError>()
        .call1((failure.to_string(),))?;
    exception.setattr("errors", &issue_objects)?;
    Ok(exception)
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
fn xvalid(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(xvalidate, m)?)?;
    m.add_class::<ValidationIssue>()?;
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
            "ValidationIssue",
            "XValidationTypeError",
            "XValidationError",
            "xvalidate",
        ],
    )?;
    Ok(())
}
